from __future__ import annotations

import inspect
import json
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Literal, cast

from loguru import logger as loguru_logger
from pydantic import Field

if TYPE_CHECKING:
    from loguru import Logger

    from nkaa.framework.logging import LogStream

from nkaa.framework.agent import AgentConfig, BaseAgent, BaseTools
from nkaa.framework.channels.models import ChannelMessage
from nkaa.framework.logging import AgentLogTool, LogPanelAdapter
from nkaa.framework.tools import ChannelTools

from .stdio_human import StdIOHumanHistory, StdIOHumanHistoryRecord

try:  # pragma: no cover - Textual は環境により未インストールの場合がある
    from textual import on
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal
    from textual.events import Mount
    from textual.reactive import reactive
    from textual.widgets import Button, Footer, Header, Input, Select, Static

    try:
        from textual.widgets import TabbedContent, TabPane
    except ImportError:  # pragma: no cover - Textual 旧バージョン対応
        TabbedContent = None  # type: ignore[assignment]
        TabPane = None  # type: ignore[assignment]

    try:  # RichLog が利用可能なら保持する
        from textual.widgets import RichLog as _RichLog
    except ImportError:  # pragma: no cover - Textual バージョン差異
        _RichLog = None  # type: ignore[assignment]

    try:
        _widgets_module = import_module("textual.widgets")
    except ImportError:  # pragma: no cover - Textual 未導入時
        _widgets_module = None

    if _widgets_module is not None:
        _candidate: type[Any] | None = None
        for name in ("TextLog", "RichLog", "Log"):
            _candidate = getattr(_widgets_module, name, None)
            if _candidate is not None:
                break
        if _candidate is None:  # pragma: no cover - 旧 API 対応
            TextLog = cast(
                type[Any],
                getattr(import_module("textual.widgets.text_log"), "TextLog"),
            )
        else:
            TextLog = _candidate
    else:  # pragma: no cover - Textual 未インストール時
        TextLog = cast(
            type[Any],
            getattr(import_module("textual.widgets.text_log"), "TextLog"),
        )
except ImportError as exc:  # pragma: no cover - 実行環境依存
    App = None
    ComposeResult = Iterable
    _TEXTUAL_IMPORT_ERROR: ImportError | None = exc
    _HAS_TABBED_CONTENT = False
    _RichLog = None  # type: ignore[assignment]
else:
    _TEXTUAL_IMPORT_ERROR = None
    _HAS_TABBED_CONTENT = TabbedContent is not None


_TextualHumanApp: type[Any]


@contextmanager
def _suppress_signal_registration_errors(log: Logger) -> Iterator[None]:
    """Temporarily suppress `signal.signal` errors outside theメインスレッド."""

    original_signal = signal.signal

    warning_emitted = False

    def safe_signal_handler(sig: int, handler: Any) -> Any:
        try:
            return original_signal(sig, handler)
        except ValueError as exc:  # pragma: no cover - signal 制限時のみ
            if "signal only works in main thread" not in str(exc):
                raise
            nonlocal warning_emitted
            if not warning_emitted:
                log.warning(
                    "Textual のシグナルハンドラを登録できませんでした。"
                    "一部の端末機能 (再描画・サスペンドなど) が無効になります。"
                )
                warning_emitted = True
            return handler

    setattr(signal, "signal", safe_signal_handler)
    try:
        yield
    finally:
        setattr(signal, "signal", original_signal)


@dataclass
class TextualHumanAgentTools(BaseTools):
    channels: ChannelTools
    log: AgentLogTool | None = None
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.channels.stop()

    def save(self) -> None:
        self.channels.save()


class TextualHumanAgent(BaseAgent[TextualHumanAgentTools]):
    """Textual ベースの人間エージェント。"""

    def __init__(
        self,
        agent_id: str,
        *,
        response_role: str = "human",
        message_field: str = "prompt",
        request_id_key: str = "request_id",
        history_path: Path | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.response_role = response_role
        self.message_field = message_field
        self.request_id_key = request_id_key
        self._request_index = 1
        self._stop_requested = False
        self._app: Any | None = None
        self._history: StdIOHumanHistory | None = StdIOHumanHistory(history_path) if history_path is not None else None
        self._last_incoming: dict[str, ChannelMessage] = {}

    def run(self, tools: TextualHumanAgentTools) -> None:
        if App is None:
            raise RuntimeError(
                "textual がインストールされていません。`pip install textual` を実行してください。"
            ) from _TEXTUAL_IMPORT_ERROR

        if tools.log is not None:
            bound_logger = tools.log.logger
        else:  # 既存互換: ログツール未提供時でも agent_id を付与して出力
            bound_logger = loguru_logger.bind(agent_id=self.agent_id)

        self._stop_requested = False
        app = _TextualHumanApp(self, tools)
        self._app = app
        try:
            if threading.current_thread() is threading.main_thread():
                app.run()
            else:
                with _suppress_signal_registration_errors(bound_logger):
                    app.run()
        finally:
            self._app = None

    def stop(self) -> None:
        self._stop_requested = True
        if self._app is not None:
            try:
                self._app.call_from_thread(self._app.request_close)
            except RuntimeError:
                # アプリが既に終了している場合は無視
                pass

    def load(self) -> None:
        if self._history is not None:
            self._history.load()

    def save(self) -> None:
        if self._history is not None:
            self._history.save()

    # ------------------------------------------------------------------
    # 呼び出し元（Textual アプリ）から利用するヘルパー
    # ------------------------------------------------------------------
    def register_incoming(self, message: ChannelMessage) -> None:
        self._last_incoming[message.channel_id] = message
        self._append_history(
            StdIOHumanHistoryRecord(
                channel_id=message.channel_id,
                direction="incoming",
                payload=message.payload,
                request_id=self.extract_request_id(message),
            )
        )

    def build_outgoing_payload(
        self,
        channel_id: str,
        content: str,
    ) -> tuple[dict[str, Any], str]:
        request_id = None
        last_message = self._last_incoming.get(channel_id)
        if last_message and isinstance(last_message.payload, dict):
            request_id = last_message.payload.get(self.request_id_key)
        if not request_id:
            request_id = self._generate_request_id()

        payload: dict[str, Any] = {
            "role": self.response_role,
            self.message_field: content,
            self.request_id_key: request_id,
        }
        return payload, request_id

    def record_outgoing(self, channel_id: str, payload: dict[str, Any]) -> None:
        self._append_history(
            StdIOHumanHistoryRecord(
                channel_id=channel_id,
                direction="outgoing",
                payload=payload,
                request_id=payload.get(self.request_id_key),
            )
        )

    def summarize_payload(self, payload: Any, *, indent: int = 2) -> str:
        if isinstance(payload, (dict, list)):
            try:
                return json.dumps(payload, ensure_ascii=False, indent=indent)
            except TypeError:
                return repr(payload)
        if isinstance(payload, str):
            return payload
        return repr(payload)

    def stop_requested(self) -> bool:
        return self._stop_requested

    def _append_history(self, record: StdIOHumanHistoryRecord) -> None:
        if self._history is None:
            return
        self._history.append(record)

    def extract_request_id(self, message: ChannelMessage) -> str | None:
        payload = message.payload
        if isinstance(payload, dict):
            value = payload.get(self.request_id_key)
            if isinstance(value, str):
                return value
        return None

    def _generate_request_id(self) -> str:
        request_id = f"human-{self._request_index:04d}"
        self._request_index += 1
        return request_id


if App is not None:

    def _create_text_log_widget(widget_id: str) -> Any:
        """Textual のバージョン差異に対応したログウィジェット生成ヘルパー。"""
        if _RichLog is not None:
            try:
                return _RichLog(
                    id=widget_id,
                    wrap=True,
                    highlight=False,
                    markup=False,
                    auto_scroll=True,
                    min_width=16,
                )
            except TypeError:  # pragma: no cover - 旧 RichLog 互換
                widget = _RichLog(id=widget_id)
                setattr(widget, "wrap", True)
                return widget

        parameters = inspect.signature(TextLog.__init__).parameters
        kwargs: dict[str, Any] = {"id": widget_id}
        if "markup" in parameters:
            kwargs["markup"] = False
        if "highlight" in parameters:
            kwargs["highlight"] = False
        return TextLog(**kwargs)

    def _create_select_widget(widget_id: str) -> Select[str]:
        """Select ウィジェットの互換生成ヘルパー。"""
        kwargs: dict[str, Any] = {
            "prompt": "送信先を選択",
            "allow_blank": False,
            "id": widget_id,
        }
        try:
            return Select[str]([("すべてのチャネル", "__all__")], **kwargs)
        except TypeError:  # pragma: no cover - 旧 API 対応
            return Select[str](**kwargs)

    def _create_log_filter_select(
        widget_id: str,
        prompt: str,
        options: list[tuple[str, str]],
    ) -> Select[str]:
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "allow_blank": False,
            "id": widget_id,
        }
        try:
            return Select[str](options, **kwargs)
        except TypeError:  # pragma: no cover - 旧 API 対応
            select = Select[str](**kwargs)
            setattr(select, "options", options)
            return select

    _LOG_LEVEL_OPTIONS: list[tuple[str, str]] = [
        ("INFO", "INFO"),
        ("TRACE", "TRACE"),
        ("DEBUG", "DEBUG"),
        ("WARNING", "WARNING"),
        ("ERROR", "ERROR"),
        ("CRITICAL", "CRITICAL"),
        ("すべて", "__all__"),
    ]

    class _RealTextualHumanApp(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }

        #app-body {
            layout: horizontal;
            height: 1fr;
        }

        #channel-panel {
            width: 32;
            border: heavy $surface;
            padding: 1;
        }

        #main-panel {
            layout: vertical;
            height: 1fr;
        }

        #chat-tab, #log-tab {
            layout: vertical;
            height: 1fr;
            padding: 1;
            border: heavy $surface;
        }

        #message-log, #log-view {
            height: 1fr;
        }

        #log-filters {
            layout: horizontal;
        }

        #status {
            height: 3;
        }
        """

        BINDINGS = [
            ("ctrl+r", "refresh_channels", "チャネル再読み込み"),
            ("ctrl+c", "quit", "終了"),
        ]

        selected_channel = reactive("__all__")

        def __init__(
            self,
            agent: TextualHumanAgent,
            tools: TextualHumanAgentTools,
        ) -> None:
            super().__init__()
            self._agent = agent
            self._tools = tools
            self._message_log: TextLog | None = None
            self._log_view: TextLog | None = None
            self._log_adapter: LogPanelAdapter | None = None
            self._log_stream: "LogStream | None" = None
            self._log_level_select: Select[str] | None = None
            self._log_agent_select: Select[str] | None = None
            self._log_channel_select: Select[str] | None = None
            self._status: Static | None = None
            self._channel_select: Select[str] | None = None
            self._input: Input | None = None
            if tools.log is not None:
                log_stream = tools.log.get_stream(level="INFO", include_agent_context=False)
                self._log_stream = log_stream
                self._log_adapter = LogPanelAdapter(
                    log_stream,
                    widget_factory=lambda: _create_text_log_widget("log-view"),
                    level="INFO",
                )
            self._stop_manager_on_shutdown = False
            self._stop_manager_called = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="app-body"):
                with Container(id="channel-panel"):
                    yield Static("送信先チャネル", id="channel-title")
                    yield _create_select_widget("channel-select")
                    yield Button("チャネルを更新", id="refresh-button")
                    yield Button("終了", id="exit-button")
                with Container(id="main-panel"):
                    if _HAS_TABBED_CONTENT:
                        with TabbedContent(initial="chat-tab", id="main-tabs"):
                            with TabPane("チャット", id="chat-tab"):
                                yield _create_text_log_widget("message-log")
                                yield Static("", id="status")
                                yield Input(
                                    placeholder="メッセージを入力 (Enter で送信)",
                                    id="message-input",
                                )
                            with TabPane("ログ", id="log-tab"):
                                if self._log_adapter is None:
                                    yield Static(
                                        "AgentLogTool が提供されていません。ログは表示できません。",
                                        id="log-empty",
                                    )
                                else:
                                    with Container(id="log-filters"):
                                        yield _create_log_filter_select(
                                            "log-level-select",
                                            "レベル",
                                            _LOG_LEVEL_OPTIONS,
                                        )
                                        yield _create_log_filter_select(
                                            "log-agent-select",
                                            "エージェント",
                                            [("すべてのエージェント", "__all__")],
                                        )
                                        yield _create_log_filter_select(
                                            "log-channel-select",
                                            "チャネル",
                                            [("すべてのチャネル", "__all__")],
                                        )
                                    yield self._log_adapter.install(self)
                    else:
                        yield _create_text_log_widget("message-log")
                        yield Static("", id="status")
                        yield Input(placeholder="メッセージを入力 (Enter で送信)", id="message-input")
                        if self._log_adapter is not None:
                            yield self._log_adapter.install(self)
                        else:
                            yield Static(
                                "AgentLogTool が提供されていません。ログは表示できません。",
                                id="log-empty",
                            )
            yield Footer()

        def on_mount(self, event: Mount) -> None:  # pragma: no cover - UI イベント
            del event
            self._message_log = cast(TextLog, self.query_one("#message-log"))
            self._status = cast(Static, self.query_one("#status"))
            self._channel_select = cast(Select[str], self.query_one("#channel-select"))
            self._input = cast(Input, self.query_one("#message-input"))
            if self._log_adapter is not None:
                self._log_view = cast(TextLog, self.query_one("#log-view"))
                if _HAS_TABBED_CONTENT:
                    self._log_level_select = cast(Select[str], self.query_one("#log-level-select"))
                    self._log_agent_select = cast(Select[str], self.query_one("#log-agent-select"))
                    self._log_channel_select = cast(Select[str], self.query_one("#log-channel-select"))
                self._log_adapter.start()
                if _HAS_TABBED_CONTENT:
                    self._refresh_log_filter_options()
                    self._apply_log_filters()
            else:
                if not _HAS_TABBED_CONTENT:
                    placeholder = self.query_one("#log-empty", Static)
                    placeholder.update("AgentLogTool が提供されていないため、ログは表示されません。")
            self._update_channel_options()
            self._set_status("Textual Human Agent is ready.")
            self._focus_input()
            self.set_interval(0.3, self._poll_messages)

        def on_shutdown(self) -> None:  # pragma: no cover - UIイベント
            if self._log_adapter is not None:
                self._log_adapter.stop()
            self._invoke_stop_manager(force=True)

        def action_refresh_channels(self) -> None:  # pragma: no cover - UIイベント
            self._update_channel_options()
            self._set_status("チャネル情報を更新しました。")

        def request_close(self) -> None:
            self.exit()

        def _update_channel_options(self) -> None:
            if self._channel_select is None:
                return
            metadata = self._tools.channels.joined_channel_metadata()
            options: list[tuple[str, str]] = [("すべてのチャネル", "__all__")]
            for meta in metadata:
                name = meta.name or meta.id
                label = f"{name}"
                options.append((label, meta.id))
            try:
                self._channel_select.set_options(options)
            except AttributeError:  # pragma: no cover - Textual バージョン差異
                setattr(self._channel_select, "options", options)
            if self.selected_channel not in {value for _, value in options}:
                self.selected_channel = "__all__"
            self._channel_select.value = self.selected_channel

        @on(Select.Changed, "#channel-select")
        def _on_channel_selected(self, event: Select.Changed[str]) -> None:  # pragma: no cover - UIイベント
            self.selected_channel = event.value or "__all__"
            self._set_status(f"送信先: {self._describe_selected_channel()}")

        @on(Select.Changed, "#log-level-select")
        def _on_log_level_changed(self, event: Select.Changed[str]) -> None:  # pragma: no cover - UIイベント
            del event
            self._apply_log_filters()

        @on(Select.Changed, "#log-agent-select")
        def _on_log_agent_changed(self, event: Select.Changed[str]) -> None:  # pragma: no cover - UIイベント
            del event
            self._apply_log_filters()

        @on(Select.Changed, "#log-channel-select")
        def _on_log_channel_changed(self, event: Select.Changed[str]) -> None:  # pragma: no cover - UIイベント
            del event
            self._apply_log_filters()

        @on(Button.Pressed, "#refresh-button")
        def _on_refresh_pressed(self) -> None:  # pragma: no cover - UIイベント
            self.action_refresh_channels()

        @on(Button.Pressed, "#exit-button")
        def _on_exit_pressed(self) -> None:  # pragma: no cover - UIイベント
            self._handle_exit_request(source="button")

        @on(Input.Submitted)
        def _on_input_submitted(self, event: Input.Submitted) -> None:  # pragma: no cover
            if event.input.id != "message-input":
                return
            content = event.value.strip()
            event.input.value = ""
            if not content:
                return
            if self._handle_command(content):
                return
            self._send_message(content)

        def _handle_command(self, content: str) -> bool:
            normalized = content.strip().lower()
            if normalized == "/help":
                self._set_status("利用可能なコマンド: /help, /quit")
                if self._input is not None:
                    self._input.value = ""
                return True
            if normalized == "/quit":
                self._handle_exit_request(source="command")
                return True
            return False

        def _handle_exit_request(self, *, source: str) -> None:
            if self._agent.stop_requested():
                self._set_status("終了処理を進めています…")
                return
            log_tool = self._tools.log
            if log_tool is not None:
                with log_tool.context(command_source=source):
                    log_tool.logger.info("quit requested")
            self._set_status("終了要求を受け付けました。まもなく終了します。")
            self._stop_manager_on_shutdown = True
            self._agent.stop()

        def _invoke_stop_manager(self, *, force: bool = False) -> None:
            if self._stop_manager_called:
                return
            if not force and not self._stop_manager_on_shutdown:
                return
            stop_manager = self._tools.stop_manager
            if stop_manager is None:
                return
            self._stop_manager_called = True
            stop_manager()

        def _send_message(self, content: str) -> None:
            targets = self._determine_targets()
            if not targets:
                self._set_status("送信先チャネルがありません。")
                return
            log_tool = self._tools.log
            for channel_id in targets:
                payload, request_id = self._agent.build_outgoing_payload(channel_id, content)
                self._tools.channels.send(channel_id, payload)
                self._agent.record_outgoing(channel_id, payload)
                channel_name = self._tools.channels.get_channel_name(channel_id)
                if log_tool is not None:
                    with log_tool.context(
                        channel_id=channel_id,
                        direction="outgoing",
                        request_id=request_id,
                    ):
                        log_tool.logger.info(
                            "sent message",
                            channel_name=channel_name,
                            payload=payload,
                        )
                self._write_log(
                    f"[OUT][{channel_name}] request_id={request_id}\n{self._agent.summarize_payload(payload)}"
                )
            self._set_status(f"送信完了: {self._describe_selected_channel()} ({len(targets)} 件)")
            self._focus_input()

        def _determine_targets(self) -> list[str]:
            metadata = {meta.id: meta for meta in self._tools.channels.joined_channel_metadata()}
            if not metadata:
                return []
            if self.selected_channel == "__all__":
                return list(metadata.keys())
            if self.selected_channel in metadata:
                return [self.selected_channel]
            return list(metadata.keys())

        def _describe_selected_channel(self) -> str:
            if self.selected_channel == "__all__":
                return "すべてのチャネル"
            name = self._tools.channels.get_channel_name(self.selected_channel)
            return name

        def _poll_messages(self) -> None:
            if self._agent.stop_requested():
                self.request_close()
                return
            received = False
            log_tool = self._tools.log
            for _ in range(8):
                message = self._tools.channels.read()
                if message is None:
                    break
                self._agent.register_incoming(message)
                channel_name = self._tools.channels.get_channel_name(message.channel_id)
                request_id = self._agent.extract_request_id(message)
                payload_text = self._agent.summarize_payload(message.payload)
                header = f"[IN ][{channel_name}]"
                if request_id:
                    header += f" request_id={request_id}"
                if log_tool is not None:
                    with log_tool.context(
                        channel_id=message.channel_id,
                        direction="incoming",
                        request_id=request_id,
                    ):
                        log_tool.logger.info(
                            "received message",
                            channel_name=channel_name,
                            payload=message.payload,
                        )
                self._write_log(f"{header}\n{payload_text}")
                received = True
            if received:
                self._focus_input()
            if self._log_adapter is not None and _HAS_TABBED_CONTENT:
                self._refresh_log_filter_options()

        def _write_log(self, text: str) -> None:
            if self._message_log is None:
                return
            self._message_log.write(text)
            self._message_log.scroll_end()

        def _set_status(self, text: str) -> None:
            if self._status is not None:
                self._status.update(text)

        def _focus_input(self) -> None:
            if self._input is not None:
                self._input.focus()

        def _apply_log_filters(self) -> None:
            if self._log_adapter is None:
                return
            level_value = "__all__"
            if self._log_level_select is not None and self._log_level_select.value:
                level_value = self._log_level_select.value
            level = None if level_value in ("", "__all__") else level_value
            if level is None:
                self._log_adapter.set_level(None)
            else:
                self._log_adapter.set_level(level)
            context_filters: dict[str, Any] = {}
            if self._log_agent_select is not None:
                agent_value = self._log_agent_select.value or "__all__"
                if agent_value not in ("", "__all__"):
                    context_filters["agent_id"] = agent_value
            if self._log_channel_select is not None:
                channel_value = self._log_channel_select.value or "__all__"
                if channel_value not in ("", "__all__"):
                    context_filters["channel_id"] = channel_value
            if context_filters:
                self._log_adapter.set_filters(**context_filters)
            else:
                self._log_adapter.set_filters()

        def _refresh_log_filter_options(self) -> None:
            if self._log_stream is None:
                return
            records = self._log_stream.snapshot()
            agent_ids = sorted(
                {
                    record.context.get("agent_id")
                    for record in records
                    if record.context.get("agent_id")
                }
            )
            channel_ids = sorted(
                {
                    record.context.get("channel_id")
                    for record in records
                    if record.context.get("channel_id")
                }
            )
            agent_options: list[tuple[str, str]] = [("すべてのエージェント", "__all__")]
            agent_options.extend((agent, agent) for agent in agent_ids)
            channel_options: list[tuple[str, str]] = [("すべてのチャネル", "__all__")]
            for channel_id in channel_ids:
                try:
                    label = self._tools.channels.get_channel_name(channel_id)
                except Exception:  # pragma: no cover - 未参加チャネルへの対応
                    label = channel_id
                channel_options.append((label, channel_id))
            self._set_select_options(self._log_agent_select, agent_options)
            self._set_select_options(self._log_channel_select, channel_options)

        def _set_select_options(
            self,
            select: Select[str] | None,
            options: list[tuple[str, str]],
        ) -> None:
            if select is None:
                return
            current = select.value or options[0][1]
            try:
                select.set_options(options)
            except AttributeError:  # pragma: no cover - Textual バージョン差異
                setattr(select, "options", options)
            values = {value for _, value in options}
            if current not in values:
                current = options[0][1]
            select.value = current

    _TextualHumanApp = _RealTextualHumanApp

else:

    class _StubTextualHumanApp:  # pragma: no cover - Textual 未導入時
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "textual がインストールされていません。`pip install textual` を実行してください。"
            ) from _TEXTUAL_IMPORT_ERROR

    _TextualHumanApp = _StubTextualHumanApp


class TextualHumanAgentConfig(AgentConfig):
    type: Literal["textual_human"] = "textual_human"
    response_role: str = Field("human", description="送信時の role フィールド値")
    message_field: str = Field("prompt", description="送信ペイロードに格納するメッセージフィールド名")
    request_id_key: str = Field("request_id", description="要求 ID を表すフィールド名")
    history_dir: Path | None = Field(
        default=None,
        description="履歴ファイルを保存するディレクトリ（未指定なら履歴を保持しない）",
    )

    def build(self) -> TextualHumanAgent:
        history_path = None
        if self.history_dir is not None:
            history_path = self.history_dir / f"{self.id}_history.jsonl"
        return TextualHumanAgent(
            agent_id=self.id,
            response_role=self.response_role,
            message_field=self.message_field,
            request_id_key=self.request_id_key,
            history_path=history_path,
        )


__all__ = [
    "TextualHumanAgent",
    "TextualHumanAgentTools",
    "TextualHumanAgentConfig",
]

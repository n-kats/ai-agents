from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import Field

from nkaa.framework.agent import AgentConfig, BaseAgent, BaseTools
from nkaa.framework.channels.models import ChannelMessage
from nkaa.framework.tools import ChannelTools

from .stdio_human import StdIOHumanHistory, StdIOHumanHistoryRecord

try:  # pragma: no cover - Textual は環境により未インストールの場合がある
    from textual import on
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal
    from textual.events import Mount
    from textual.reactive import reactive
    from textual.widgets import Button, Footer, Header, Input, Select, Static, TextLog
except ImportError as exc:  # pragma: no cover - 実行環境依存
    App = None  # type: ignore[assignment]
    ComposeResult = Iterable  # type: ignore[assignment]
    _TEXTUAL_IMPORT_ERROR: ImportError | None = exc
else:
    _TEXTUAL_IMPORT_ERROR = None


@dataclass
class TextualHumanAgentTools(BaseTools):
    channels: ChannelTools

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
        self._app: _TextualHumanApp | None = None
        self._history: StdIOHumanHistory | None = (
            StdIOHumanHistory(history_path) if history_path is not None else None
        )
        self._last_incoming: dict[str, ChannelMessage] = {}

    def run(self, tools: TextualHumanAgentTools) -> None:
        if App is None:
            raise RuntimeError(
                "textual がインストールされていません。`pip install textual` を実行してください。"
            ) from _TEXTUAL_IMPORT_ERROR

        self._stop_requested = False
        app = _TextualHumanApp(self, tools)
        self._app = app
        try:
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

    class _TextualHumanApp(App[None]):  # type: ignore[type-arg]
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

        #log-panel {
            layout: vertical;
            height: 1fr;
        }

        #message-input {
            dock: bottom;
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
            self._log: TextLog | None = None
            self._status: Static | None = None
            self._channel_select: Select[str] | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="app-body"):
                with Container(id="channel-panel"):
                    yield Static("送信先チャネル", id="channel-title")
                    yield Select[str](
                        id="channel-select",
                        prompt="送信先を選択",
                        allow_blank=False,
                    )
                    yield Button("チャネルを更新", id="refresh-button")
                with Container(id="log-panel"):
                    yield TextLog(id="log", markup=False, highlight=False)
                    yield Static("", id="status")
                    yield Input(placeholder="メッセージを入力 (Enter で送信)", id="message-input")
            yield Footer()

        def on_mount(self, event: Mount) -> None:  # pragma: no cover - UI イベント
            del event
            self._log = self.query_one(TextLog)
            self._status = self.query_one(Static, "#status")
            self._channel_select = self.query_one(Select)
            self._update_channel_options()
            self._set_status("Textual Human Agent is ready.")
            self.set_interval(0.3, self._poll_messages)

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
                self._channel_select.options = options  # type: ignore[attr-defined]
            if self.selected_channel not in {value for _, value in options}:
                self.selected_channel = "__all__"
            self._channel_select.value = self.selected_channel

        @on(Select.Changed)
        def _on_channel_selected(self, event: Select.Changed[str]) -> None:  # pragma: no cover - UIイベント
            self.selected_channel = event.value or "__all__"
            self._set_status(f"送信先: {self._describe_selected_channel()}")

        @on(Button.Pressed, "#refresh-button")
        def _on_refresh_pressed(self) -> None:  # pragma: no cover - UIイベント
            self.action_refresh_channels()

        @on(Input.Submitted)
        def _on_input_submitted(self, event: Input.Submitted) -> None:  # pragma: no cover
            if event.input.id != "message-input":
                return
            content = event.value.strip()
            event.input.value = ""
            if not content:
                return
            self._send_message(content)

        def _send_message(self, content: str) -> None:
            targets = self._determine_targets()
            if not targets:
                self._set_status("送信先チャネルがありません。")
                return
            for channel_id in targets:
                payload, request_id = self._agent.build_outgoing_payload(channel_id, content)
                self._tools.channels.send(channel_id, payload)
                self._agent.record_outgoing(channel_id, payload)
                channel_name = self._tools.channels.get_channel_name(channel_id)
                self._write_log(
                    f"[OUT][{channel_name}] request_id={request_id}\n{self._agent.summarize_payload(payload)}"
                )
            self._set_status(
                f"送信完了: {self._describe_selected_channel()} ({len(targets)} 件)"
            )

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
                self._write_log(f"{header}\n{payload_text}")

        def _write_log(self, text: str) -> None:
            if self._log is None:
                return
            self._log.write(text)
            self._log.scroll_end()

        def _set_status(self, text: str) -> None:
            if self._status is not None:
                self._status.update(text)

else:

    class _TextualHumanApp:  # pragma: no cover - Textual 未導入時
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "textual がインストールされていません。`pip install textual` を実行してください。"
            ) from _TEXTUAL_IMPORT_ERROR


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

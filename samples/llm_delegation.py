"""最小限の LLM デリゲーションサンプル。"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable, Literal, Type, cast
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    StandardManager,
    StandardManagerConfig,
    ThreadingManagerExecutionBackend,
)
from nkaa.framework.channels import ChannelManager, DatabaseChannelConfig, InMemoryChannelRepository
from nkaa.framework.channels.message_routing import ChannelMessageRouteProvider
from nkaa.framework.channels.models import ChannelMessage, ChannelMetadata
from nkaa.framework.message_manager import MessageManager
from nkaa.framework.messages import StopMessage
from nkaa.framework.logging import AgentLogTool, configure_logging, get_log_stream
from nkaa.framework.tools import ChannelTools, MessageTools
from nkaa.presets.agents import (
    StdIOHumanAgentConfig,
    StdIOHumanAgentTools,
    TextualHumanAgent,
    TextualHumanAgentConfig,
    TextualHumanAgentTools,
)
from nkaa.presets.tools import LLMCallTool

ANALYSIS_CHANNEL_NAME = "analysis_workspace"
HUMAN_CHANNEL_NAME = "human_support"
ANALYSIS_CHANNEL_DESCRIPTION = "分析担当LLMがアウトラインを元に考察を行うワークスペース。"
HUMAN_CHANNEL_DESCRIPTION = "人間ユーザーとの対話を行う窓口チャネル。"

FRONT_DESK_SYSTEM_PROMPT = dedent(
    """
    あなたは受付エージェントです。
    user メッセージには incoming_channel と incoming_message が含まれています。
    incoming_message は辞書型で、human_support から届くときは
    {"role": "human", "prompt": <本文>, "request_id": <任意>} の形式です。
    analysis_workspace から届くときは
    {"role": "analysis_summary", "content": <要約>, "request_id": <任意>} です。

    受付エージェントの出力は JSON オブジェクト 1 つのみです。
    JSON の全フィールドはダブルクオートで囲み、余計な文字列やコードブロックを付けないでください。
    返却フォーマット:
    {
      "output_channel": "<available_channels.channel_name のいずれか>",
      "message": {
        "role": "<チャネルへ投稿するメッセージ種別>",
        "content": "<本文>",
        "request_id": "<任意の文字列または省略可>",
        "metadata": <任意の辞書または省略可>
      }
    }

    incoming_channel.channel_name が "human_support" の場合:
      * output_channel は "analysis_workspace" を指定する。
      * message.role は "analysis_request"。
      * message.content には incoming_message["prompt"] を読み取り、
        要約や確認事項、次のアクション案を箇条書きで整理して入れる。
      * incoming_message に request_id があれば message.request_id にそのまま引き継ぐ。

    incoming_channel.channel_name が "analysis_workspace" で
    incoming_message.role が "analysis_summary" の場合:
      * output_channel は "human_support" を指定する。
      * message.role は "analysis_summary"。
      * message.content には incoming_message["content"] を転記し、
        人間ユーザーにそのまま届ける。
      * request_id が存在するなら message.request_id に設定する。

    上記以外のケースでは JSON を返さず、何も出力しない。
    """
).strip()

THINKING_SYSTEM_PROMPT = dedent(
    """
    あなたは分析担当です。
    incoming_channel.channel_name が "analysis_workspace" で
    incoming_message.role が "analysis_request" の場合のみ対応します。
    incoming_message は {"role": "analysis_request", "content": <受付エージェントの要約>,
    "request_id": <任意>} の形式です。

    出力は JSON オブジェクト 1 つのみとし、以下のフォーマットに厳密に従ってください。
    余計な説明やコードブロックは付けないでください。
    {
      "output_channel": "<available_channels.channel_name のいずれか>",
      "message": {
        "role": "<チャネルへ投稿するメッセージ種別>",
        "content": "<本文>",
        "request_id": "<任意の文字列または省略可>",
        "metadata": <任意の辞書または省略可>
      }
    }

    * output_channel には通常 "analysis_workspace" を指定する。
    * message.role は必ず "analysis_summary"。
    * message.content には human_support へ伝える分析サマリー、結論、推奨アクションを日本語で記述する。
      箇条書きや番号付きリストを活用して読みやすくまとめる。
    * incoming_message に request_id が含まれていれば message.request_id に引き継ぐ。
    * metadata が不要な場合は省略する。

    条件に合わないメッセージを受け取った場合は何も出力しない。
    """
).strip()

_LLM_CALL_LOG_DIR = Path("_tmp/samples/llm_delegation/llm_calls")


def _channel_display_name(metadata: ChannelMetadata) -> str:
    return metadata.name or metadata.id


def _summarize_payload(payload: Any, *, limit: int = 160) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False) if isinstance(
            payload, (dict, list)) else str(payload)
    except Exception:  # pragma: no cover - 予期せぬシリアライズ失敗時
        text = repr(payload)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class StructuredChannelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str
    request_id: str | None = None
    metadata: dict[str, str] | None = None


class StructuredChannelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_channel: str
    message: StructuredChannelMessage


@dataclass
class DelegationManagerTools(BaseTools):
    channel_manager: ChannelManager
    message_manager: MessageManager
    llm: LLMCallTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.llm.stop()

    def save(self) -> None:
        self.llm.save()


@dataclass
class DelegationAgentTools(BaseTools):
    channels: ChannelTools
    messages: MessageTools
    llm: LLMCallTool
    log: AgentLogTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.channels.stop()
        self.messages.stop()
        self.llm.stop()

    def save(self) -> None:
        self.channels.save()
        self.messages.save()
        self.llm.save()

    def joined_channel_metadata(self) -> list[ChannelMetadata]:
        return list(self.channels.joined_channel_metadata())


class DelegationLLMAgent(BaseAgent[DelegationAgentTools]):
    def __init__(
        self,
        agent_id: str,
        *,
        system_prompt: str,
        model: str,
        shutdown_grace_period: float = 5.0,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.system_prompt = system_prompt
        self._shutdown_grace_period = shutdown_grace_period
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._inflight_tasks: set[asyncio.Task[Any]] = set()
        self._pending_stop: bool = False
        self._history_pointers: list[tuple[str, int]] = []

    def stop(self) -> None:
        self._pending_stop = True
        loop = self._loop
        stop_event = self._stop_event
        if loop is None or stop_event is None:
            return

        def _propagate_stop() -> None:
            self._pending_stop = False
            if not stop_event.is_set():
                stop_event.set()

        loop.call_soon_threadsafe(_propagate_stop)

    def load(self) -> None:  # pragma: no cover
        return None

    def save(self) -> None:  # pragma: no cover
        return None

    def run(self, tools: DelegationAgentTools) -> None:
        asyncio.run(self.run_async(tools))

    async def _cancel_task(self, task: asyncio.Task[Any]) -> None:
        if task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _await_llm_dispatch(
        self,
        task: asyncio.Task[Any],
        stop_event: asyncio.Event,
        *,
        poll_interval: float = 0.1,
    ) -> StructuredChannelResponse:
        while True:
            if stop_event.is_set():
                if task.done():
                    return await task
                graceful_timeout = max(self._shutdown_grace_period, 0.0)
                if graceful_timeout > 0:
                    try:
                        return await asyncio.wait_for(task, timeout=graceful_timeout)
                    except asyncio.TimeoutError:
                        pass
                await self._cancel_task(task)
                raise asyncio.CancelledError
            try:
                return await asyncio.wait_for(task, timeout=poll_interval)
            except asyncio.TimeoutError:
                await asyncio.sleep(0)

    def _store_pointer(self, message: ChannelMessage) -> tuple[str, int]:
        pointer = (message.channel_id, message.message_id)
        self._history_pointers.append(pointer)
        return pointer

    async def _log_history_snapshot(
        self,
        tools: DelegationAgentTools,
        agent_logger: Any,
        log_tool: AgentLogTool | None,
        channel_id: str,
        *,
        max_entries: int = 5,
    ) -> None:
        if not self._history_pointers:
            return
        pointers = tuple(self._history_pointers[-max_entries:])
        history = await asyncio.to_thread(tools.messages.fetch_messages, pointers)
        entries = [
            {
                "channel_id": msg.channel_id,
                "message_id": msg.message_id,
                "role": msg.payload.get("role") if isinstance(msg.payload, dict) else None,
                "summary": _summarize_payload(msg.payload, limit=60),
            }
            for msg in history
        ]
        with (log_tool.context(channel_id=channel_id) if log_tool else nullcontext()):
            agent_logger.debug(
                "Fetched history entries via fetch_messages() (latest={}): {}",
                len(entries),
                entries,
            )

    async def run_async(self, tools: DelegationAgentTools) -> None:
        log_tool = tools.log
        agent_logger = (
            log_tool.logger if log_tool is not None else logger.bind(
                agent_id=self.agent_id)
        )
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        self._loop = loop
        self._stop_event = stop_event
        if self._pending_stop:
            stop_event.set()
            self._pending_stop = False
        try:
            while not stop_event.is_set():
                try:
                    incoming = await tools.messages.read_async(
                        poll_interval=0.5,
                        stop_event=stop_event,
                    )
                except asyncio.CancelledError:
                    break
                if isinstance(incoming, StopMessage):
                    agent_logger.info(
                        "Received stop signal; shutting down agent {}", self.agent_id)
                    break
                message = incoming
                if message is None:
                    await asyncio.sleep(0)
                    continue
                if message.sender_id == self.agent_id:
                    continue
                if not isinstance(message.payload, dict):
                    with (log_tool.context(channel_id=message.channel_id) if log_tool else nullcontext()):
                        agent_logger.warning(
                            "Skipping non-dict payload from channel {}: {!r}",
                            message.channel_id,
                            message.payload,
                        )
                    continue
                payload = message.payload
                channel_metadata = tools.joined_channel_metadata()
                if not channel_metadata:
                    agent_logger.warning(
                        "Agent {} is not joined to any channels", self.agent_id)
                    await asyncio.sleep(0)
                    continue
                incoming = next(
                    (meta for meta in channel_metadata if meta.id == message.channel_id), None)
                if incoming is None:
                    with (log_tool.context(channel_id=message.channel_id) if log_tool else nullcontext()):
                        agent_logger.debug(
                            "Skipping message from unexpected channel {}",
                            message.channel_id,
                        )
                    continue
                with (log_tool.context(channel_id=message.channel_id) if log_tool else nullcontext()):
                    agent_logger.info(
                        "Agent {} received message via {} from {}: {}",
                        self.agent_id,
                        _channel_display_name(incoming),
                        message.sender_id,
                        _summarize_payload(payload),
                    )
                    self._store_pointer(message)
                await self._log_history_snapshot(tools, agent_logger, log_tool, message.channel_id)
                available_channels = [
                    {
                        "channel_name": _channel_display_name(meta),
                        "channel_description": meta.description or "",
                    }
                    for meta in channel_metadata
                ]
                llm_task = asyncio.create_task(
                    invoke_structured_llm(
                        tools.llm,
                        model=self.model,
                        system_prompt=self.system_prompt,
                        payload={
                            "incoming_channel": {
                                "channel_id": incoming.id,
                                "channel_name": _channel_display_name(incoming),
                                "channel_description": incoming.description or "",
                            },
                            "incoming_message": payload,
                            "available_channels": available_channels,
                        },
                        log=log_tool,
                    ),
                    name=f"llm-call-{self.agent_id}",
                )
                self._inflight_tasks.add(llm_task)
                try:
                    dispatch = await self._await_llm_dispatch(llm_task, stop_event)
                except asyncio.CancelledError:
                    break
                finally:
                    self._inflight_tasks.discard(llm_task)
                if stop_event.is_set():
                    break
                target: str | None = None
                trimmed = dispatch.output_channel.strip()
                if trimmed:
                    for meta in channel_metadata:
                        if _channel_display_name(meta) == trimmed:
                            target = meta.id
                            break
                    else:
                        with (log_tool.context(channel_id=message.channel_id) if log_tool else nullcontext()):
                            agent_logger.warning(
                                "Unknown output channel '{}' from agent {}; falling back",
                                dispatch.output_channel,
                                self.agent_id,
                            )
                if target is None:
                    with (log_tool.context(channel_id=message.channel_id) if log_tool else nullcontext()):
                        agent_logger.warning(
                            "No output channel resolved; returning to source {}",
                            message.channel_id,
                        )
                    target = message.channel_id
                outgoing = dispatch.message.model_dump()
                await tools.messages.send_async(target, outgoing)
                target_meta = next(
                    (meta for meta in channel_metadata if meta.id == target), None)
                target_label = _channel_display_name(
                    target_meta) if target_meta else target
                with (log_tool.context(channel_id=target) if log_tool else nullcontext()):
                    agent_logger.info(
                        "Sent message to {} with role={}",
                        target_label,
                        outgoing.get("role"),
                    )
        finally:
            pending = tuple(self._inflight_tasks)
            self._inflight_tasks.clear()
            if pending:
                timeout = max(self._shutdown_grace_period, 0.0)
                if timeout > 0:
                    gather_task = asyncio.gather(
                        *pending, return_exceptions=True)
                    try:
                        await asyncio.wait_for(asyncio.shield(gather_task), timeout=timeout)
                    except asyncio.TimeoutError:
                        with (log_tool.context() if log_tool else nullcontext()):
                            agent_logger.warning(
                                "Timed out waiting for %d inflight LLM task(s) to finish; forcing shutdown",
                                len([task for task in pending if not task.done()]),
                            )
                        for task in pending:
                            await self._cancel_task(task)
                        await gather_task
                else:
                    for task in pending:
                        await self._cancel_task(task)
                    await asyncio.gather(*pending, return_exceptions=True)
            self._loop = None
            self._stop_event = None
            self._pending_stop = False
            self._history_pointers.clear()


async def invoke_structured_llm(
    llm: LLMCallTool,
    *,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    log: AgentLogTool | None = None,
) -> StructuredChannelResponse:
    # format_messages = []
    # format_message = "\n".join(format_messages)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        # {"role": "user", "content": f"上記の内容に基づいて対応してください。\n{format_message}"
    ]
    incoming = payload.get("incoming_channel", {})
    if isinstance(incoming, dict):
        channel_name = incoming.get("channel_name", "n/a")
        channel_id = incoming.get("channel_id")
    else:
        channel_name = "n/a"
        channel_id = None

    def _context() -> Any:
        return log.context(channel_id=channel_id) if log else nullcontext()

    bound_logger = log.logger if log else logger
    call_record: dict[str, Any] = {
        "call_id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(),
        "model": model,
        "channel_name": channel_name,
        "channel_id": channel_id,
        "system_prompt": system_prompt,
        "messages": messages,
        "payload": payload,
    }
    with _context():
        bound_logger.info("LLM call channel={} model={}", channel_name, model)
    try:
        result = await llm.call_parsed_async(
            messages,
            parse_model=StructuredChannelResponse,
            model_name=model,
        )
        call_record["status"] = "ok"
        call_record["response"] = result.model_dump()
        log_path = await asyncio.to_thread(_write_llm_call_log, call_record)
        with _context():
            bound_logger.debug("Saved LLM call debug log at {}", str(log_path))
        return result
    except asyncio.CancelledError:
        call_record["status"] = "cancelled"
        log_path = await asyncio.to_thread(_write_llm_call_log, call_record)
        with _context():
            bound_logger.warning(
                "LLM call cancelled. channel={} model={} log={}",
                channel_name,
                model,
                str(log_path),
            )
        raise
    except Exception:
        prompt_dump = json.dumps(messages, ensure_ascii=False, indent=2)
        payload_dump = json.dumps(payload, ensure_ascii=False, indent=2)
        call_record["status"] = "error"
        call_record["prompt_dump"] = prompt_dump
        call_record["payload_dump"] = payload_dump
        log_path = await asyncio.to_thread(_write_llm_call_log, call_record)
        with _context():
            bound_logger.error(
                "LLM call failed. system_prompt={}\nmessages={}\npayload={}\nlog={}",
                system_prompt,
                prompt_dump,
                payload_dump,
                str(log_path),
            )
        raise


def delegation_adapter(agent: BaseAgent[Any], manager_tools: DelegationManagerTools) -> BaseTools:
    base_channel_tools = ChannelTools(
        agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    message_tools = MessageTools(
        agent_id=agent.agent_id, manager=manager_tools.message_manager)
    log_tool = AgentLogTool(agent_id=agent.agent_id)
    if isinstance(agent, DelegationLLMAgent):
        return DelegationAgentTools(
            channels=base_channel_tools,
            messages=message_tools,
            llm=manager_tools.llm,
            log=log_tool,
            stop_manager=manager_tools.stop_manager,
        )
    if isinstance(agent, TextualHumanAgent):
        return TextualHumanAgentTools(
            channels=base_channel_tools,
            messages=message_tools,
            log=log_tool,
            stop_manager=manager_tools.stop_manager,
        )
    return StdIOHumanAgentTools(channels=base_channel_tools, messages=message_tools)


class DelegationLLMAgentConfig(AgentConfig):
    type: Literal["delegation_llm"] = "delegation_llm"
    system_prompt: str
    model: str = Field("gpt-5-mini")
    shutdown_grace_period: float = Field(5.0, ge=0.0)

    def build(self) -> DelegationLLMAgent:
        return DelegationLLMAgent(
            agent_id=self.id,
            model=self.model,
            system_prompt=self.system_prompt,
            shutdown_grace_period=self.shutdown_grace_period,
        )


AGENT_TYPE_REGISTRY: dict[str, Type[AgentConfig]] = {
    "stdio_human": StdIOHumanAgentConfig,
    "textual_human": TextualHumanAgentConfig,
    "delegation_llm": DelegationLLMAgentConfig,
}


class DelegationManagerConfig(StandardManagerConfig):
    config_dir: Path

    def get_agent_config_paths(self) -> list[Path]:
        return sorted(self.config_dir.glob("*.json"))

    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        try:
            return AGENT_TYPE_REGISTRY[type_name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent type: {type_name}") from exc

    def build_tools(self) -> DelegationManagerTools:
        repository = InMemoryChannelRepository()
        channel_manager = ChannelManager(repository)
        route_provider = ChannelMessageRouteProvider(channel_manager)
        message_manager = MessageManager(repository, route_provider)
        channel_manager.attach_unread_handler(message_manager)
        return DelegationManagerTools(
            channel_manager=channel_manager,
            message_manager=message_manager,
            llm=LLMCallTool(),
        )


def configure_delegation_channels(manager: StandardManager) -> None:
    tools = cast(DelegationManagerTools, manager.tools)
    channel_manager = tools.channel_manager

    front_desk = manager.get_agent(
        "front_desk_agent",
        expected_type=DelegationLLMAgent,
    )
    thinker = manager.get_agent(
        "thinking_agent",
        expected_type=DelegationLLMAgent,
    )
    human = manager.get_agent(
        "human",
        expected_type=TextualHumanAgent,
    )

    human_channel_id = channel_manager.create(
        DatabaseChannelConfig(
            name=HUMAN_CHANNEL_NAME,
            description=HUMAN_CHANNEL_DESCRIPTION,
        )
    ).id
    analysis_channel_id = channel_manager.create(
        DatabaseChannelConfig(
            name=ANALYSIS_CHANNEL_NAME,
            description=ANALYSIS_CHANNEL_DESCRIPTION,
        )
    ).id

    channel_manager.join_agent(human_channel_id, front_desk.agent_id)
    channel_manager.join_agent(analysis_channel_id, front_desk.agent_id)
    channel_manager.join_agent(analysis_channel_id, thinker.agent_id)
    channel_manager.join_agent(human_channel_id, human.agent_id)


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def prepare_configs(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    history_dir = base_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for config_path in base_dir.glob("*.json"):
        config_path.unlink()
    configs: Iterable[tuple[str, dict[str, Any]]] = [
        (
            "01_textual_human.json",
            {
                "type": "textual_human",
                "id": "human",
                "response_role": "human",
                "history_dir": str(history_dir),
            },
        ),
        (
            "02_front_desk.json",
            {
                "type": "delegation_llm",
                "id": "front_desk_agent",
                "model": "gpt-5-mini",
                "system_prompt": FRONT_DESK_SYSTEM_PROMPT,
            },
        ),
        (
            "03_thinking_llm.json",
            {
                "type": "delegation_llm",
                "id": "thinking_agent",
                "model": "gpt-5-mini",
                "system_prompt": THINKING_SYSTEM_PROMPT,
            },
        ),
    ]
    for filename, data in configs:
        _write_config(base_dir / filename, data)


def _collect_channel_histories(tools: DelegationManagerTools) -> list[dict[str, Any]]:
    """チャネルごとのメッセージ履歴をまとめたデータ構造を生成する。"""

    channel_manager = tools.channel_manager
    message_manager = tools.message_manager

    collected: list[dict[str, Any]] = []
    for channel_id, channel in sorted(
        channel_manager.list_channels().items(),
        key=lambda item: (item[1].metadata.name or item[0]),
    ):
        metadata = channel.metadata
        messages = message_manager.list_channel_messages(channel_id)
        collected.append(
            {
                "channel_id": channel_id,
                "label": metadata.name or channel_id,
                "description": metadata.description or "",
                "messages": [
                    {
                        "message_id": message.message_id,
                        "sender_id": message.sender_id,
                        "created_at": message.created_at,
                        "summary": _summarize_payload(message.payload, limit=80),
                    }
                    for message in messages
                ],
            }
        )
    return collected


def _collect_agent_logs(*, level: str = "INFO") -> list[dict[str, Any]]:
    """エージェント別のログスナップショットを取得する。"""

    stream = get_log_stream(level=level)
    try:
        records = stream.snapshot()
    finally:
        stream.close()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        agent_id = record.context.get("agent_id")
        key = agent_id if isinstance(agent_id, str) else "system"
        context_items = {
            key_name: value
            for key_name, value in sorted(record.context.items())
            if key_name != "agent_id"
        }
        grouped[key].append(
            {
                "level": record.level,
                "timestamp": record.timestamp,
                "message": record.message,
                "context": context_items,
            }
        )

    return [
        {"agent_id": agent_id, "entries": entries}
        for agent_id, entries in sorted(grouped.items())
    ]


def _render_report_fallback(channel_histories: list[dict[str, Any]], agent_logs: list[dict[str, Any]]) -> None:
    """チャネル履歴とログ集計をシステムログへ書き出す。"""

    report_logger = logger.bind(agent_id="system", section="summary_report")

    history_lines: list[str] = ["=== チャネル履歴 ==="]
    if not channel_histories:
        history_lines.append("チャネルはまだ作成されていません。")
    for channel in channel_histories:
        description = f" {channel['description']}" if channel["description"] else ""
        history_lines.append(
            f"- {channel['label']} ({channel['channel_id']}){description}")
        if not channel["messages"]:
            history_lines.append("    (メッセージなし)")
            continue
        for message in channel["messages"]:
            created_at = message["created_at"].strftime("%H:%M:%S")
            message_no = message["message_id"] if message["message_id"] is not None else "?"
            history_lines.append(
                f"    #{message_no} {created_at} {message['sender_id']}: {message['summary']}"
            )

    report_logger.info("\n".join(history_lines))

    log_lines: list[str] = ["=== エージェント別ログ（INFO 以上） ==="]
    if not agent_logs:
        log_lines.append("ログは出力されませんでした。")
    for block in agent_logs:
        label = block["agent_id"] if block["agent_id"] != "system" else "システム"
        log_lines.append(f"- {label}")
        for entry in block["entries"]:
            timestamp = entry["timestamp"].strftime("%H:%M:%S")
            if entry["context"]:
                context_suffix = " ".join(
                    f"{k}={v}" for k, v in entry["context"].items())
                context_text = f" {context_suffix}"
            else:
                context_text = ""
            log_lines.append(
                f"    [{entry['level']}] {timestamp} {entry['message']}{context_text}")

    report_logger.info("\n".join(log_lines))


def _show_report_cui(tools: DelegationManagerTools) -> None:
    channel_histories = _collect_channel_histories(tools)
    agent_logs = _collect_agent_logs()
    _render_report_fallback(channel_histories, agent_logs)


def _write_llm_call_log(entry: dict[str, Any]) -> Path:
    _LLM_CALL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = entry.get("timestamp") or datetime.now().astimezone().isoformat()
    call_id = entry.setdefault("call_id", str(uuid4()))
    safe_timestamp = timestamp.replace(":", "-").replace("+", "_").replace(" ", "_")
    filename = f"{safe_timestamp}_{call_id}.json"
    path = _LLM_CALL_LOG_DIR / filename
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_demo() -> None:
    # Textual CUI でログを確認する前提のため、コンソールシンクは無効化
    configure_logging(buffer_limit=500)
    logger.info("Starting delegation demo setup")
    config_dir = Path("_tmp/samples/llm_delegation")
    prepare_configs(config_dir)
    manager = StandardManager.initialize_or_load(
        config_dir,
        config_factory=lambda path: DelegationManagerConfig(config_dir=path),
        adapter=delegation_adapter,
        execution_backend=ThreadingManagerExecutionBackend(),
    )
    tools = cast(DelegationManagerTools, manager.tools)
    tools.stop_manager = manager.create_stop_event_tool()
    configure_delegation_channels(manager)
    manager.run()
    _show_report_cui(tools)


if __name__ == "__main__":
    run_demo()

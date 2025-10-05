"""最小限の LLM デリゲーションサンプル。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type, cast

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
from nkaa.framework.channels.models import ChannelMetadata
from nkaa.framework.message_manager import MessageManager
from nkaa.framework.messages import StopMessage
from nkaa.framework.logging import AgentLogTool, configure_logging
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

FRONT_DESK_SYSTEM_PROMPT = (
    "あなたは受付エージェントです。"
    "user メッセージには incoming_channel と incoming_message が含まれています。"
    "incoming_channel.channel_name が 'human_support' のときは、"
    "依頼内容を整理したアウトラインを作り"
    "analysis_workspace に送るための analysis_request メッセージを構築してください。"
    "incoming_channel.channel_name が 'analysis_workspace' で "
    "incoming_message.role が 'analysis_summary' のときは、"
    "要約をそのまま human_support へ届けるためのメッセージを作成してください。"
    "その他のケースでは出力せず無視します。"
    "message には必ず role（例: analysis_request）と content（要約本文）を含め、"
    "必要なら request_id を文字列で設定してください。"
    "Responses API の structured_output 機能で `StructuredChannelResponse` スキーマ（"
    "output_channel: str, message: {role: str, content: str, "
    "request_id: Optional[str], metadata: Optional[dict[str, str]]}）"
    "が適用されています。"
    "構造化スキーマに適合するデータのみを返し、周囲に説明やコードブロック、余計な文字列を絶対に付与しないでください。"
    "output_channel には available_channels.channel_name のいずれかを正確に指定し、"
    "message.role と message.content は要件に沿った値にしてください。"
)

THINKING_SYSTEM_PROMPT = (
    "あなたは分析担当です。"
    "incoming_channel.channel_name が 'analysis_workspace' で "
    "incoming_message.role が 'analysis_request' のときだけ対応し、"
    "human_support の依頼内容とアウトラインを読み取って分析サマリー・結論・推奨アクションをまとめてください。"
    "結果は analysis_workspace に投稿し、role は 'analysis_summary' に設定してください。"
    "message には role と content（分析結果テキスト）を必ず含め、"
    "必要に応じて request_id を文字列で設定してください。"
    "該当しないメッセージは無視します。"
    "Responses API の structured_output 機能で `StructuredChannelResponse` スキーマが適用されています。"
    "構造化スキーマに合致する出力のみを返し、余計なテキストは一切付けないでください。"
    "output_channel には available_channels.channel_name のいずれかを指定し、"
    "message.role は 'analysis_summary'、message.content には分析結果を記載してください。"
)


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
            for task in list(self._inflight_tasks):
                task.cancel()

        loop.call_soon_threadsafe(_propagate_stop)

    def load(self) -> None:  # pragma: no cover
        return None

    def save(self) -> None:  # pragma: no cover
        return None

    def run(self, tools: DelegationAgentTools) -> None:
        asyncio.run(self.run_async(tools))

    async def _await_llm_dispatch(
        self,
        task: asyncio.Task[Any],
        stop_event: asyncio.Event,
        *,
        poll_interval: float = 0.1,
    ) -> StructuredChannelResponse:
        while True:
            if stop_event.is_set():
                task.cancel()
            try:
                return await asyncio.wait_for(task, timeout=poll_interval)
            except asyncio.TimeoutError:
                if stop_event.is_set():
                    task.cancel()
                    raise asyncio.CancelledError
                await asyncio.sleep(0)

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
                for task in pending:
                    task.cancel()
                if self._shutdown_grace_period > 0:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*pending, return_exceptions=True),
                            timeout=self._shutdown_grace_period,
                        )
                    except asyncio.TimeoutError:
                        with (log_tool.context() if log_tool else nullcontext()):
                            agent_logger.warning(
                                "Timed out waiting for %d inflight LLM task(s) to finish; forcing shutdown",
                                len(pending),
                            )
                for task in pending:
                    if not task.done():
                        task.cancel()
            self._loop = None
            self._stop_event = None
            self._pending_stop = False


async def invoke_structured_llm(
    llm: LLMCallTool,
    *,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    log: AgentLogTool | None = None,
) -> StructuredChannelResponse:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
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
    with _context():
        bound_logger.info("LLM call channel={} model={}", channel_name, model)
    try:
        return await llm.call_parsed_async(
            messages,
            parse_model=StructuredChannelResponse,
            model_name=model,
        )
    except asyncio.CancelledError:
        with _context():
            bound_logger.warning(
                "LLM call cancelled. channel={} model={}", channel_name, model)
        raise
    except Exception:
        prompt_dump = json.dumps(messages, ensure_ascii=False, indent=2)
        payload_dump = json.dumps(payload, ensure_ascii=False, indent=2)
        with _context():
            bound_logger.error(
                "LLM call failed. system_prompt={}\nmessages={}\npayload={}",
                system_prompt,
                prompt_dump,
                payload_dump,
            )
        raise


def delegation_adapter(agent: BaseAgent[Any], manager_tools: DelegationManagerTools) -> BaseTools:
    base_channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    message_tools = MessageTools(agent_id=agent.agent_id, manager=manager_tools.message_manager)
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
                "model": "gpt-5-nano",
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


if __name__ == "__main__":
    run_demo()

"""最小限の LLM デリゲーションサンプル。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Type, cast

from pydantic import BaseModel, Field

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    StandardManager,
    StandardManagerConfig,
    ThreadingManagerExecutionBackend,
)
from nkaa.framework.channels import ChannelManager, DatabaseChannelConfig, InMemoryChannelRepository
from nkaa.framework.tools import ChannelTools
from nkaa.presets.agents import StdIOHumanAgent, StdIOHumanAgentConfig, StdIOHumanAgentTools
from nkaa.presets.tools import LLMCallTool


logger = logging.getLogger(__name__)

ANALYSIS_CHANNEL_NAME = "analysis_workspace"
HUMAN_CHANNEL_NAME = "human_support"

FRONT_DESK_SYSTEM_PROMPT = (
    "あなたは受付エージェントです。依頼を整理し、分析担当が扱えるように短いアウトラインを作成してください。"
    '必ず {"output_channel": "...", "message": {...}} の JSON だけを返してください。'
)

THINKING_SYSTEM_PROMPT = (
    "あなたは分析担当です。依頼とアウトラインを読み、サマリー・結論・推奨アクションを返してください。"
    '必ず {"output_channel": "...", "message": {...}} の JSON だけを返してください。'
)


class StructuredChannelResponse(BaseModel):
    output_channel: str
    message: dict[str, Any]


@dataclass
class DelegationManagerTools(BaseTools):
    channel_manager: ChannelManager
    llm: LLMCallTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.llm.stop()

    def save(self) -> None:
        self.llm.save()


@dataclass
class DelegationAgentTools(BaseTools):
    channels: ChannelTools
    llm: LLMCallTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.channels.stop(); self.llm.stop()

    def save(self) -> None:
        self.channels.save(); self.llm.save()


class DelegationLLMAgent(BaseAgent[DelegationAgentTools]):
    def __init__(
        self,
        agent_id: str,
        *,
        role: Literal["front_desk", "thinking"],
        model: str,
        analysis_channel_name: str = ANALYSIS_CHANNEL_NAME,
        human_channel_name: str | None = None,
    ) -> None:
        if role == "front_desk" and human_channel_name is None:
            raise ValueError("Front desk role requires a human channel name.")
        self.agent_id = agent_id
        self.role = role
        self.model = model
        self.analysis_channel_name = analysis_channel_name
        self.human_channel_name = human_channel_name

    def stop(self) -> None:  # pragma: no cover
        return None

    def load(self) -> None:  # pragma: no cover
        return None

    def save(self) -> None:  # pragma: no cover
        return None

    def run(self, tools: DelegationAgentTools) -> None:
        channels = self._channel_map(tools)
        analysis_id = channels.get(self.analysis_channel_name)
        if analysis_id is None:
            raise RuntimeError("Delegation agent requires an analysis channel.")
        human_id = channels.get(self.human_channel_name) if self.human_channel_name else analysis_id
        watched = [analysis_id] if human_id == analysis_id else [human_id, analysis_id]
        available_channels = self._available_channels()

        while True:
            message = tools.channels.receive(channels=watched, block=True, timeout=1.0)
            if message is None or message.sender_id == self.agent_id:
                continue
            payload = message.payload if isinstance(message.payload, dict) else None
            if payload is None:
                continue
            if self.role == "front_desk":
                self._handle_front_desk_payload(
                    tools,
                    channels,
                    available_channels,
                    analysis_id,
                    human_id,
                    message.channel_id,
                    payload,
                )
            else:
                self._handle_thinking_payload(
                    tools,
                    channels,
                    available_channels,
                    analysis_id,
                    payload,
                )

    def _handle_front_desk_payload(
        self,
        tools: DelegationAgentTools,
        channels: dict[str, str],
        available_channels: list[str],
        analysis_id: str,
        human_id: str,
        channel_id: str,
        payload: dict[str, Any],
    ) -> None:
        if channel_id == human_id:
            dispatch = invoke_structured_llm(
                tools.llm,
                model=self.model,
                system_prompt=FRONT_DESK_SYSTEM_PROMPT,
                payload={
                    "request_id": str(payload.get("request_id", "")) or "request",
                    "prompt": str(payload.get("prompt", "")),
                    "available_channels": available_channels,
                },
            )
            target = self._channel_id_for_name(dispatch.output_channel, channels, analysis_id)
            tools.channels.send(
                target,
                with_defaults(
                    {"role": "analysis_request", **dispatch.message},
                    request_id=payload.get("request_id", "request"),
                    original_prompt=payload.get("prompt", ""),
                    outline=payload.get("prompt", "依頼を整理してください。"),
                ),
            )
            return

        if payload.get("role") != "analysis_summary":
            return
        tools.channels.send(human_id, payload)
        if callable(tools.stop_manager):
            tools.stop_manager()

    def _handle_thinking_payload(
        self,
        tools: DelegationAgentTools,
        channels: dict[str, str],
        available_channels: list[str],
        analysis_id: str,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("role") != "analysis_request":
            return
        outline = str(payload.get("outline", ""))
        prompt = str(payload.get("original_prompt", outline))
        request_id = str(payload.get("request_id", "")) or "request"
        dispatch = invoke_structured_llm(
            tools.llm,
            model=self.model,
            system_prompt=THINKING_SYSTEM_PROMPT,
            payload={
                "request_id": request_id,
                "human_request": prompt,
                "front_desk_outline": outline,
                "available_channels": available_channels,
            },
            max_output_tokens=600,
        )
        target = self._channel_id_for_name(dispatch.output_channel, channels, analysis_id)
        tools.channels.send(
            target,
            with_defaults(
                {"role": "analysis_summary", **dispatch.message},
                request_id=request_id,
                summary=outline or prompt,
                conclusion="追加の検討が必要です。",
                action_items=[],
                risks=[],
                assumptions=[],
            ),
        )

    def _available_channels(self) -> list[str]:
        names = [self.analysis_channel_name]
        if self.human_channel_name:
            names.append(self.human_channel_name)
        return sorted({name for name in names if name})

    def _channel_map(self, tools: DelegationAgentTools) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for channel_id in tools.channels.joined_channels():
            mapping[tools.channels.get_channel_name(channel_id)] = channel_id
        return mapping

    def _channel_id_for_name(self, name: str, mapping: dict[str, str], default: str) -> str:
        trimmed = name.strip()
        return mapping.get(trimmed, default)


def invoke_structured_llm(
    llm: LLMCallTool,
    *,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    max_output_tokens: int | None = None,
) -> StructuredChannelResponse:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    logger.info("LLM call role=%s request=%s", payload.get("role", "n/a"), payload.get("request_id"))
    return llm.call_parsed(
        messages,
        parse_model=StructuredChannelResponse,
        model_name=model,
        max_output_tokens=max_output_tokens,
    )


def with_defaults(data: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    for key, default in defaults.items():
        data.setdefault(key, default)
    return data


def delegation_adapter(agent: BaseAgent[Any], manager_tools: DelegationManagerTools) -> BaseTools:
    channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    if isinstance(agent, DelegationLLMAgent):
        return DelegationAgentTools(channels=channel_tools, llm=manager_tools.llm, stop_manager=manager_tools.stop_manager)
    return StdIOHumanAgentTools(channels=channel_tools)


class DelegationLLMAgentConfig(AgentConfig):
    type: Literal["delegation_llm"] = "delegation_llm"
    role: Literal["front_desk", "thinking"]
    model: str = Field("gpt-5-mini")

    def build(self) -> DelegationLLMAgent:
        return DelegationLLMAgent(
            agent_id=self.id,
            role=self.role,
            model=self.model,
            human_channel_name=HUMAN_CHANNEL_NAME if self.role == "front_desk" else None,
        )


AGENT_TYPE_REGISTRY: dict[str, Type[AgentConfig]] = {
    "stdio_human": StdIOHumanAgentConfig,
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
        manager = ChannelManager(repository)
        return DelegationManagerTools(channel_manager=manager, llm=LLMCallTool())


def configure_delegation_channels(manager: StandardManager) -> None:
    tools = cast(DelegationManagerTools, manager.tools)
    channel_manager = tools.channel_manager

    front_desk = next((agent for agent in manager.agents if isinstance(agent, DelegationLLMAgent) and agent.role == "front_desk"), None)
    thinker = next((agent for agent in manager.agents if isinstance(agent, DelegationLLMAgent) and agent.role == "thinking"), None)
    human = next((agent for agent in manager.agents if isinstance(agent, StdIOHumanAgent)), None)

    if front_desk is None or thinker is None or human is None:
        raise RuntimeError("llm_delegation sample expects front desk, thinking, and human agents.")

    human_channel_id = channel_manager.create(
        DatabaseChannelConfig(name=front_desk.human_channel_name or "human_support")
    ).id
    analysis_channel_id = channel_manager.create(
        DatabaseChannelConfig(name=front_desk.analysis_channel_name)
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
            "01_stdio_human.json",
            {
                "type": "stdio_human",
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
                "role": "front_desk",
                "model": "gpt-5-nano",
            },
        ),
        (
            "03_thinking_llm.json",
            {
                "type": "delegation_llm",
                "id": "thinking_agent",
                "role": "thinking",
                "model": "gpt-5-mini",
            },
        ),
    ]
    for filename, data in configs:
        _write_config(base_dir / filename, data)


def run_demo() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
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

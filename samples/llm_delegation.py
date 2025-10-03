"""最小限の LLM デリゲーションサンプル。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type, cast

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
from nkaa.framework.channels.models import ChannelMetadata
from nkaa.framework.tools import ChannelTools
from nkaa.presets.agents import StdIOHumanAgent, StdIOHumanAgentConfig, StdIOHumanAgentTools
from nkaa.presets.tools import LLMCallTool


logger = logging.getLogger(__name__)

ANALYSIS_CHANNEL_NAME = "analysis_workspace"
HUMAN_CHANNEL_NAME = "human_support"
ANALYSIS_CHANNEL_DESCRIPTION = "分析担当LLMがアウトラインを元に考察を行うワークスペース。"
HUMAN_CHANNEL_DESCRIPTION = "人間ユーザーとの対話を行う窓口チャネル。"

FRONT_DESK_SYSTEM_PROMPT = (
    "あなたは受付エージェントです。"
    "user メッセージには incoming_channel と incoming_message が含まれています。"
    "incoming_channel.channel_name が 'human_support' のときは、依頼内容を整理したアウトラインを作り"
    "analysis_workspace に送るための analysis_request メッセージを構築してください。"
    "incoming_channel.channel_name が 'analysis_workspace' で incoming_message.role が 'analysis_summary' のときは、"
    "要約をそのまま human_support へ届けるためのメッセージを作成してください。"
    "その他のケースでは出力せず無視します。"
    "message には必ず role（例: analysis_request）と content（要約本文）を含め、必要なら request_id を文字列で設定してください。"
    "Responses API の structured_output 機能で `StructuredChannelResponse` スキーマ（"
    "output_channel: str, message: {role: str, content: str, request_id: Optional[str], metadata: Optional[dict[str, str]]}）"
    "が適用されています。"
    "構造化スキーマに適合するデータのみを返し、周囲に説明やコードブロック、余計な文字列を絶対に付与しないでください。"
    "output_channel には available_channels.channel_name のいずれかを正確に指定し、"
    "message.role と message.content は要件に沿った値にしてください。"
)

THINKING_SYSTEM_PROMPT = (
    "あなたは分析担当です。"
    "incoming_channel.channel_name が 'analysis_workspace' で incoming_message.role が 'analysis_request' のときだけ対応し、"
    "human_support の依頼内容とアウトラインを読み取って分析サマリー・結論・推奨アクションをまとめてください。"
    "結果は analysis_workspace に投稿し、role は 'analysis_summary' に設定してください。"
    "message には role と content（分析結果テキスト）を必ず含め、必要に応じて request_id を文字列で設定してください。"
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
        text = (
            json.dumps(payload, ensure_ascii=False)
            if isinstance(payload, (dict, list))
            else str(payload)
        )
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
    llm: LLMCallTool

    def stop(self) -> None:
        self.llm.stop()

    def save(self) -> None:
        self.llm.save()


@dataclass
class DelegationAgentTools(BaseTools):
    channels: ChannelTools
    llm: LLMCallTool

    def stop(self) -> None:
        self.channels.stop()
        self.llm.stop()

    def save(self) -> None:
        self.channels.save()
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
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.system_prompt = system_prompt

    def stop(self) -> None:  # pragma: no cover
        return None

    def load(self) -> None:  # pragma: no cover
        return None

    def save(self) -> None:  # pragma: no cover
        return None

    def run(self, tools: DelegationAgentTools) -> None:
        while True:
            message = tools.channels.read(block=True)
            if message is None or message.sender_id == self.agent_id:
                continue
            if not isinstance(message.payload, dict):
                logger.warning(
                    "Skipping non-dict payload from channel %s: %r",
                    message.channel_id,
                    message.payload,
                )
                continue
            payload = message.payload
            channel_metadata = tools.joined_channel_metadata()
            if not channel_metadata:
                logger.warning("Agent %s is not joined to any channels", self.agent_id)
                continue
            incoming = next((meta for meta in channel_metadata if meta.id == message.channel_id), None)
            if incoming is None:
                logger.debug("Skipping message from unexpected channel %s", message.channel_id)
                continue
            logger.info(
                "Agent %s received message via %s from %s: %s",
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
            dispatch = invoke_structured_llm(
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
            )
            target: str | None = None
            trimmed = dispatch.output_channel.strip()
            if trimmed:
                for meta in channel_metadata:
                    if _channel_display_name(meta) == trimmed:
                        target = meta.id
                        break
                else:
                    logger.warning(
                        "Unknown output channel '%s' from agent %s; falling back",
                        dispatch.output_channel,
                        self.agent_id,
                    )
            if target is None:
                logger.warning(
                    "No output channel resolved; returning to source %s",
                    message.channel_id,
                )
                target = message.channel_id
            tools.channels.send(target, dispatch.message.model_dump())


def invoke_structured_llm(
    llm: LLMCallTool,
    *,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
) -> StructuredChannelResponse:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    incoming = payload.get("incoming_channel", {})
    channel_name = incoming.get("channel_name") if isinstance(incoming, dict) else "n/a"
    logger.info("LLM call channel=%s model=%s", channel_name, model)
    try:
        return llm.call_parsed(
            messages,
            parse_model=StructuredChannelResponse,
            model_name=model,
        )
    except Exception as exc:
        prompt_dump = json.dumps(messages, ensure_ascii=False, indent=2)
        payload_dump = json.dumps(payload, ensure_ascii=False, indent=2)
        logger.error(
            "LLM call failed. system_prompt=%s\nmessages=%s\npayload=%s",
            system_prompt,
            prompt_dump,
            payload_dump,
        )
        raise


def delegation_adapter(agent: BaseAgent[Any], manager_tools: DelegationManagerTools) -> BaseTools:
    base_channel_tools = ChannelTools(agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    if isinstance(agent, DelegationLLMAgent):
        return DelegationAgentTools(channels=base_channel_tools, llm=manager_tools.llm)
    return StdIOHumanAgentTools(channels=base_channel_tools)


class DelegationLLMAgentConfig(AgentConfig):
    type: Literal["delegation_llm"] = "delegation_llm"
    system_prompt: str
    model: str = Field("gpt-5-mini")

    def build(self) -> DelegationLLMAgent:
        return DelegationLLMAgent(
            agent_id=self.id,
            model=self.model,
            system_prompt=self.system_prompt,
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
        expected_type=StdIOHumanAgent,
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
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    config_dir = Path("_tmp/samples/llm_delegation")
    prepare_configs(config_dir)
    manager = StandardManager.initialize_or_load(
        config_dir,
        config_factory=lambda path: DelegationManagerConfig(config_dir=path),
        adapter=delegation_adapter,
        execution_backend=ThreadingManagerExecutionBackend(),
    )
    configure_delegation_channels(manager)
    manager.run()


if __name__ == "__main__":
    run_demo()

"""InMemory リポジトリを用いた LLM エージェント協調サンプル。"""

from __future__ import annotations

import json
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
from nkaa.framework.channels import (
    ChannelManager,
    ChannelSearchQuery,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.tools import ChannelTools
from nkaa.presets.agents import StdIOHumanAgentConfig, StdIOHumanAgentTools
from nkaa.presets.tools import LLMCallTool

OUTLINE_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "DelegationOutline",
    "schema": {
        "type": "object",
        "properties": {
            "heading": {
                "type": "string",
                "description": "アウトラインに付与する見出し。省略時は分析タスクを示す。",
            },
            "items": {
                "type": "array",
                "description": "依頼内容を整理した箇条書き（最大5項目）",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}


SUMMARY_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "AnalysisSummary",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "分析担当が提案内容を箇条書きや段落で整理したテキスト",
            },
            "conclusion": {
                "type": "string",
                "description": "最終的な推奨アクションや結論を一文で示す",
            },
            "action_items": {
                "type": "array",
                "description": "次に取るべき推奨アクションを重要度順に並べたリスト",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "risks": {
                "type": "array",
                "description": "実行時に留意すべきリスクや懸念事項",
                "items": {"type": "string"},
                "minItems": 0,
            },
            "assumptions": {
                "type": "array",
                "description": "提案が成り立つ前提条件や追加で確認すべき点",
                "items": {"type": "string"},
                "minItems": 0,
            },
        },
        "required": ["summary", "conclusion", "action_items"],
        "additionalProperties": False,
    },
}


@dataclass
class AnalysisResult:
    summary: str
    conclusion: str
    action_items: list[str]
    risks: list[str]
    assumptions: list[str]


def generate_analysis_outline(llm: LLMCallTool, prompt: str, model: str) -> str:
    """フロント担当が分析者向けに依頼内容を要約する。"""

    response = llm.create_response(
        [
            {
                "role": "system",
                "content": (
                    "あなたはフロントデスク担当です。ユーザーからの依頼を受け取り、"
                    "分析担当が作業しやすいようにタスクの要点と完了条件を最大5項目で整理します。"
                    "出力は JSON 形式で、{\"heading\": \"分析タスク:\", \"items\": [\"...\"]} のような"
                    "オブジェクト1つのみを返してください。heading を省略する場合は '分析タスク:' を使用し、"
                    "items には日本語の短い箇条書き文を含めてください。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model_name=model,
        response_format={
            "type": "json_schema",
            "json_schema": OUTLINE_RESPONSE_SCHEMA,
        },
    )
    outline = llm.extract_output_text(response)
    if not outline:
        raise RuntimeError("LLM から分析用ブリーフが返りませんでした。")
    try:
        data = json.loads(outline)
    except json.JSONDecodeError:
        return outline.strip()

    heading = str(data.get("heading", "分析タスク:")).strip() or "分析タスク:"
    raw_items = data.get("items", [])
    items = [str(item).strip() for item in raw_items if str(item).strip()]
    if not items:
        return outline.strip()

    lines = [heading]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def generate_summary(
    llm: LLMCallTool, original_prompt: str, outline: str, model: str
) -> AnalysisResult:
    """分析担当が最終サマリーと結論を生成する。"""

    response = llm.create_response(
        [
            {
                "role": "system",
                "content": (
                    "あなたは分析担当です。以下の人間からの依頼とフロントデスクの整理メモを読み、"
                    "実行案をまとめます。必ず JSON 形式で {\"summary\": \"...\", \"conclusion\": \"...\","
                    " \"action_items\": [\"...\"], \"risks\": [\"...\"], \"assumptions\": [\"...\"]} のみを返してください。"
                    "summary には依頼全体の要約を 2〜3 文程度で記述し、conclusion には最終的な推奨アクションを"
                    "一文で示してください。action_items には優先度順の具体的な次のアクションを、risks には想定されるリスクや注意点を、"
                    "assumptions には提案が成立するために確認すべき前提条件を記載してください。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "human_request": original_prompt,
                        "front_desk_outline": outline,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        model_name=model,
        response_format={
            "type": "json_schema",
            "json_schema": SUMMARY_RESPONSE_SCHEMA,
        },
        max_output_tokens=600,
    )
    text = llm.extract_output_text(response)
    if not text:
        raise RuntimeError("LLM からサマリー出力が得られませんでした。")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        summary = text.strip()
        conclusion = "提案内容を参照してください。"
        action_items = [summary] if summary else []
        risks: list[str] = []
        assumptions: list[str] = []
    else:
        summary = str(data.get("summary", "")).strip()
        conclusion = str(data.get("conclusion", "")).strip()
        raw_action_items = data.get("action_items", [])
        raw_risks = data.get("risks", [])
        raw_assumptions = data.get("assumptions", [])

        action_items = [str(item).strip() for item in raw_action_items if str(item).strip()]
        risks = [str(item).strip() for item in raw_risks if str(item).strip()]
        assumptions = [str(item).strip() for item in raw_assumptions if str(item).strip()]

        if not summary:
            summary = "\n".join(action_items) if action_items else text.strip()
        if not conclusion:
            conclusion = "提案内容を参照してください。"
        if not action_items and summary:
            action_items = [summary]

    return AnalysisResult(
        summary=summary.strip(),
        conclusion=conclusion,
        action_items=action_items,
        risks=risks,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# ツールと共通ユーティリティ
# ---------------------------------------------------------------------------


@dataclass
class DelegationManagerTools(BaseTools):
    channel_manager: ChannelManager
    llm: LLMCallTool
    stop_manager: Callable[[], None] | None = None

    def stop(self) -> None:
        self.llm.stop()

    def save(self) -> None:
        self.llm.save()


def delegation_adapter(
    agent: BaseAgent[StdIOHumanAgentTools],
    manager_tools: DelegationManagerTools,
) -> StdIOHumanAgentTools:
    channel_tools = ChannelTools(
        agent_id=agent.agent_id,
        manager=manager_tools.channel_manager,
    )
    tools = StdIOHumanAgentTools(channels=channel_tools)
    attach_llm = getattr(agent, "attach_llm_tool", None)
    if callable(attach_llm):
        attach_llm(manager_tools.llm)
    return tools


class ChannelDescriptor(BaseModel):
    name: str
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def to_config(self) -> DatabaseChannelConfig:
        return DatabaseChannelConfig(
            name=self.name,
            description=self.description,
            attributes=self.attributes,
        )


def ensure_channel(descriptor: ChannelDescriptor, tools: StdIOHumanAgentTools) -> str:
    existing = tools.channels.search(
        ChannelSearchQuery(name=descriptor.name,
                           attributes=descriptor.attributes)
    )
    created = False
    if existing:
        channel_id = existing[0].id
    else:
        channel = tools.channels.manager.create(descriptor.to_config())
        channel_id = channel.id
        created = True

    if channel_id not in tools.channels.joined_channels():
        tools.channels.join(channel_id)

    if created:
        description = descriptor.description or f"{descriptor.name} のディスカッション"
        attributes_summary = "、".join(
            f"{key}={value}" for key, value in sorted(descriptor.attributes.items())
        )
        guidance_lines = [f"チャンネルテーマ: {description}"]
        if attributes_summary:
            guidance_lines.append(f"属性: {attributes_summary}")
        guidance_lines.append("このチャンネルの目的に沿った最初のメッセージを投稿してください。")

        tools.channels.send(
            channel_id,
            {
                "role": "system",
                "prompt": "\n".join(guidance_lines),
                "channel_name": descriptor.name,
            },
            metadata={"seed_message": True},
        )

    return channel_id


class BaseDelegationAgent(BaseAgent[StdIOHumanAgentTools]):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._stop_manager: Callable[[], None] = lambda: None
        self._llm_tool: LLMCallTool | None = None

    def stop(self) -> None:
        return None

    def load(self) -> None:
        return None

    def save(self) -> None:
        return None

    def attach_stop_manager(self, stop_manager: Callable[[], None]) -> None:
        self._stop_manager = stop_manager

    def trigger_stop_manager(self) -> None:
        self._stop_manager()

    def attach_llm_tool(self, llm_tool: LLMCallTool) -> None:
        self._llm_tool = llm_tool

    def _require_llm_tool(self) -> LLMCallTool:
        if self._llm_tool is None:
            raise RuntimeError("LLMCallTool がアタッチされていません。")
        return self._llm_tool


# ---------------------------------------------------------------------------
# エージェント実装
# ---------------------------------------------------------------------------


class FrontDeskAgent(BaseDelegationAgent):
    """人間とのやり取りを担い、分析エージェントへ依頼を転送する担当。"""

    def __init__(
        self,
        agent_id: str,
        human_channel: ChannelDescriptor,
        analysis_channel: ChannelDescriptor,
        outline_model: str = "gpt-5-nano",
    ) -> None:
        super().__init__(agent_id)
        self.human_channel_descriptor = human_channel
        self.analysis_channel_descriptor = analysis_channel
        self.outline_model = outline_model
        self.forwarded: set[str] = set()
        self.completed: set[str] = set()
        self.pending: dict[str, dict[str, str]] = {}

    def run(self, tools: StdIOHumanAgentTools) -> None:
        llm = self._require_llm_tool()
        human_channel_id = ensure_channel(self.human_channel_descriptor, tools)
        analysis_channel_id = ensure_channel(
            self.analysis_channel_descriptor, tools)

        tools.channels.join(human_channel_id)
        tools.channels.join(analysis_channel_id)

        self._forward_human_requests(
            llm, tools, human_channel_id, analysis_channel_id)
        self._deliver_summaries(tools, human_channel_id, analysis_channel_id)

    def _forward_human_requests(
        self,
        llm: LLMCallTool,
        tools: StdIOHumanAgentTools,
        human_channel_id: str,
        analysis_channel_id: str,
    ) -> None:
        idle_cycles = 0
        max_idle_cycles = 5
        while idle_cycles < max_idle_cycles:
            message = tools.channels.read(
                channels=[human_channel_id], block=True, timeout=1.0
            )
            if message is None:
                idle_cycles += 1
                continue

            idle_cycles = 0
            payload = message.payload
            if not isinstance(payload, dict) or payload.get("role") != "human":
                continue

            request_id = payload.get("request_id")
            if not request_id or request_id in self.forwarded:
                continue

            prompt = payload.get("prompt", "")
            outline = generate_analysis_outline(llm, prompt, self.outline_model)
            analysis_payload = {
                "role": "analysis_request",
                "request_id": request_id,
                "original_prompt": prompt,
                "outline": outline,
            }
            tools.channels.send(analysis_channel_id, analysis_payload)
            self.forwarded.add(request_id)
            self.pending[request_id] = {"prompt": prompt}
            print(
                f"[FrontDesk] forwarded request {request_id} -> analysis channel", flush=True)

    def _deliver_summaries(
        self,
        tools: StdIOHumanAgentTools,
        human_channel_id: str,
        analysis_channel_id: str,
    ) -> None:
        idle_cycles = 0
        max_idle_cycles = 5
        while idle_cycles < max_idle_cycles:
            message = tools.channels.read(
                channels=[analysis_channel_id], block=True, timeout=1.0
            )
            if message is None:
                idle_cycles += 1
                continue

            idle_cycles = 0
            payload = message.payload
            if not isinstance(payload, dict) or payload.get("role") != "analysis_summary":
                continue

            request_id = payload.get("request_id")
            if not request_id or request_id in self.completed:
                continue

            original_prompt = self.pending.get(
                request_id, {}).get("prompt", "")
            summary_payload = {
                "role": "assistant",
                "request_id": request_id,
                "prompt": original_prompt,
                "summary": payload.get("summary", ""),
                "conclusion": payload.get("conclusion", ""),
                "action_items": list(payload.get("action_items", [])),
                "risks": list(payload.get("risks", [])),
                "assumptions": list(payload.get("assumptions", [])),
            }
            tools.channels.send(human_channel_id, summary_payload)
            self.completed.add(request_id)
            self.pending.pop(request_id, None)
            print(
                f"[FrontDesk] delivered summary for {request_id} back to human channel",
                flush=True,
            )

            if not self.pending:
                self.trigger_stop_manager()


class AnalystAgent(BaseDelegationAgent):
    """タスク内容を分析し、要約を生成するエージェント。"""

    def __init__(self, agent_id: str, analysis_channel: ChannelDescriptor, model: str = "gpt-5-mini") -> None:
        super().__init__(agent_id)
        self.analysis_channel_descriptor = analysis_channel
        self.model = model
        self.processed: set[str] = set()

    def run(self, tools: StdIOHumanAgentTools) -> None:
        llm = self._require_llm_tool()
        analysis_channel_id = ensure_channel(
            self.analysis_channel_descriptor, tools)
        tools.channels.join(analysis_channel_id)

        idle_cycles = 0
        max_idle_cycles = 5
        while idle_cycles < max_idle_cycles:
            message = tools.channels.read(
                channels=[analysis_channel_id], block=True, timeout=1.0
            )
            if message is None:
                idle_cycles += 1
                continue

            idle_cycles = 0
            payload = message.payload
            if not isinstance(payload, dict) or payload.get("role") != "analysis_request":
                continue

            request_id = payload.get("request_id")
            if not request_id or request_id in self.processed:
                continue

            outline = payload.get("outline", "")
            original_prompt = payload.get("original_prompt", outline)
            result = generate_summary(llm, original_prompt, outline, self.model)
            response_payload = {
                "role": "analysis_summary",
                "request_id": request_id,
                "summary": result.summary,
                "conclusion": result.conclusion,
                "action_items": result.action_items,
                "risks": result.risks,
                "assumptions": result.assumptions,
            }
            tools.channels.send(analysis_channel_id, response_payload)
            self.processed.add(request_id)
            print(f"[Analyst] completed analysis for {request_id}", flush=True)


# ---------------------------------------------------------------------------
# AgentConfig 実装
# ---------------------------------------------------------------------------


class FrontDeskAgentConfig(AgentConfig):
    type: Literal["front_desk"] = "front_desk"
    human_channel: ChannelDescriptor
    analysis_channel: ChannelDescriptor
    outline_model: str = Field("gpt-5-nano", description="依頼要約に利用するモデル名")

    def build(self) -> FrontDeskAgent:
        return FrontDeskAgent(
            agent_id=self.id,
            human_channel=self.human_channel,
            analysis_channel=self.analysis_channel,
            outline_model=self.outline_model,
        )


class AnalystAgentConfig(AgentConfig):
    type: Literal["analyst"] = "analyst"
    analysis_channel: ChannelDescriptor
    model: str = Field("gpt-5-mini", description="分析サマリー生成に利用するモデル名")

    def build(self) -> AnalystAgent:
        return AnalystAgent(agent_id=self.id, analysis_channel=self.analysis_channel, model=self.model)


AGENT_TYPE_REGISTRY: dict[str, Type[AgentConfig]] = {
    "stdio_human": StdIOHumanAgentConfig,
    "front_desk": FrontDeskAgentConfig,
    "analyst": AnalystAgentConfig,
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


def create_delegation_manager(config_dir: Path) -> StandardManager[
    DelegationManagerConfig, DelegationManagerTools, StdIOHumanAgentTools
]:
    config = DelegationManagerConfig(config_dir=config_dir)

    def _load_tools(self: StandardManager[
        DelegationManagerConfig, DelegationManagerTools, StdIOHumanAgentTools
    ]) -> DelegationManagerTools:
        repository = InMemoryChannelRepository()
        manager = ChannelManager(repository)
        llm_tool = LLMCallTool()
        return DelegationManagerTools(channel_manager=manager, llm=llm_tool)

    manager_obj = cast(
        StandardManager[DelegationManagerConfig, DelegationManagerTools, StdIOHumanAgentTools],
        object.__new__(StandardManager),
    )
    bound_loader = _load_tools.__get__(manager_obj, StandardManager)  # type: ignore[arg-type]
    setattr(manager_obj, "_load_tools", bound_loader)
    StandardManager.__init__(
        manager_obj,
        config,
        delegation_adapter,
        execution_backend=ThreadingManagerExecutionBackend(),
    )

    if isinstance(manager_obj.tools, DelegationManagerTools):
        stop_manager = manager_obj.create_stop_event_tool()
        manager_obj.tools.stop_manager = stop_manager
        for agent in manager_obj.agents:
            attach = getattr(agent, "attach_stop_manager", None)
            if callable(attach):
                attach(stop_manager)
    return manager_obj


# ---------------------------------------------------------------------------
# 設定生成とデモ実行
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def prepare_configs(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    history_dir = base_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    human_channel = {
        "name": "human_support",
        "description": "Human <-> Front desk conversation",
        "attributes": {"purpose": "llm_delegation"},
    }
    analysis_channel = {
        "name": "analysis_workspace",
        "description": "Front desk <-> Analyst collaboration",
        "attributes": {"purpose": "llm_delegation"},
    }

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
                "type": "front_desk",
                "id": "front_agent",
                "human_channel": human_channel,
                "analysis_channel": analysis_channel,
                "outline_model": "gpt-5-nano",
            },
        ),
        (
            "03_analyst.json",
            {
                "type": "analyst",
                "id": "analyst_agent",
                "analysis_channel": analysis_channel,
                "model": "gpt-5-mini",
            },
        ),
    ]

    for filename, data in configs:
        _write_config(base_dir / filename, data)


def run_demo() -> None:
    config_dir = Path("_tmp/samples/llm_delegation")
    prepare_configs(config_dir)
    manager = create_delegation_manager(config_dir)

    agents = {agent.agent_id: agent for agent in manager.agents}
    front_desk_config_path = config_dir / "02_front_desk.json"
    if front_desk_config_path.exists():
        config_data = json.loads(front_desk_config_path.read_text())
        human_channel_cfg = config_data.get("human_channel")
        if isinstance(human_channel_cfg, dict) and "human" in agents:
            human_descriptor = ChannelDescriptor.model_validate(human_channel_cfg)
            human_tools = manager.apply_adapter(agents["human"])
            human_channel_id = ensure_channel(human_descriptor, human_tools)
            human_tools.channels.join(human_channel_id)

    manager.run()


if __name__ == "__main__":
    run_demo()

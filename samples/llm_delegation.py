"""InMemory リポジトリを用いた LLM エージェント協調サンプル。"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Type

from pydantic import BaseModel, Field

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    StandardManager,
    StandardManagerConfig,
)
from nkaa.framework.channels import (
    ChannelManager,
    ChannelSearchQuery,
    DatabaseChannelConfig,
    InMemoryChannelRepository,
)
from nkaa.framework.tools import ChannelTools

# `multiprocessing.Event` が利用できない環境向けに `StandardManager` が参照する
# イベント実装を `threading.Event` へ差し替える。
import nkaa.framework.agent as agent_module


agent_module.Event = threading.Event


try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - 依存が無い場合の補助メッセージ
    OpenAI = None  # type: ignore[assignment]
    _OPENAI_IMPORT_ERROR = exc
else:
    _OPENAI_IMPORT_ERROR = None


_OPENAI_CLIENT: Any = None


def get_openai_client() -> Any:
    """OpenAI クライアントを初期化して返す。"""

    if OpenAI is None:
        raise RuntimeError(
            "openai パッケージが見つかりません。`pip install openai` を実行してください。"
        ) from _OPENAI_IMPORT_ERROR

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY が設定されていません。OpenAI の API キーを環境変数に設定してください。"
        )

    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is None:
        _OPENAI_CLIENT = OpenAI(api_key=api_key)
    return _OPENAI_CLIENT


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


def generate_analysis_outline(prompt: str, model: str) -> str:
    """フロント担当が分析者向けに依頼内容を要約する。"""

    client = get_openai_client()
    response = client.responses.create(
        model=model,
        input=[
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
        response_format={
            "type": "json_schema",
            "json_schema": OUTLINE_RESPONSE_SCHEMA,
        },
    )
    outline = _extract_output_text(response)
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


def generate_summary(original_prompt: str, outline: str, model: str) -> AnalysisResult:
    """分析担当が最終サマリーと結論を生成する。"""

    client = get_openai_client()
    response = client.responses.create(
        model=model,
        input=[
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
        response_format={
            "type": "json_schema",
            "json_schema": SUMMARY_RESPONSE_SCHEMA,
        },
        max_output_tokens=600,
    )
    text = _extract_output_text(response)
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


def _extract_output_text(response: Any) -> str:
    """Responses API からテキスト出力を可能な限り抽出するヘルパ。"""

    if hasattr(response, "output_text") and response.output_text:
        return str(response.output_text).strip()

    def _maybe_text(node: Any) -> str | None:
        if node is None:
            return None
        if isinstance(node, str):
            return node
        if isinstance(node, (list, tuple)):
            parts: list[str] = []
            for item in node:
                maybe = _maybe_text(item)
                if maybe:
                    parts.append(maybe)
            if parts:
                return "\n".join(parts)
            return None
        if isinstance(node, dict):
            if "value" in node and isinstance(node["value"], str):
                return node["value"]
            if "text" in node:
                return _maybe_text(node["text"])
            if "content" in node:
                return _maybe_text(node["content"])
            parts: list[str] = []
            for value in node.values():
                maybe = _maybe_text(value)
                if maybe:
                    parts.append(maybe)
            if parts:
                return "\n".join(parts)
            return None
        if hasattr(node, "value") and isinstance(getattr(node, "value"), str):
            return getattr(node, "value")
        if hasattr(node, "text"):
            return _maybe_text(getattr(node, "text"))
        if hasattr(node, "content"):
            return _maybe_text(getattr(node, "content"))
        if hasattr(node, "model_dump"):
            return _maybe_text(node.model_dump())  # type: ignore[arg-type]
        return None

    parts: list[str] = []

    output = getattr(response, "output", None)
    if output:
        for item in output:
            maybe = _maybe_text(getattr(item, "content", None))
            if maybe:
                parts.append(maybe)

    if not parts:
        data = getattr(response, "data", None)
        if data:
            for item in data:
                maybe = _maybe_text(getattr(item, "content", None))
                if maybe:
                    parts.append(maybe)

    if not parts and hasattr(response, "choices"):
        for choice in getattr(response, "choices", []):
            maybe = _maybe_text(getattr(choice, "message", None))
            if maybe:
                parts.append(maybe)

    if not parts and hasattr(response, "model_dump"):
        dumped = response.model_dump()  # type: ignore[attr-defined]
        maybe = _maybe_text(dumped)
        if maybe:
            parts.append(maybe)

    aggregated = "\n".join(part.strip() for part in parts if part)
    if aggregated.strip():
        return aggregated.strip()

    return str(response)


# ---------------------------------------------------------------------------
# ツールと共通ユーティリティ
# ---------------------------------------------------------------------------


@dataclass
class DelegationManagerTools(BaseTools):
    channel_manager: ChannelManager

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


@dataclass
class DelegationAgentTools(BaseTools):
    channels: ChannelTools

    def stop(self) -> None:
        return None

    def save(self) -> None:
        return None


def delegation_adapter(
    agent: BaseAgent[DelegationAgentTools],
    manager_tools: DelegationManagerTools,
) -> DelegationAgentTools:
    channel_tools = ChannelTools(
        agent_id=agent.agent_id, manager=manager_tools.channel_manager)
    return DelegationAgentTools(channels=channel_tools)


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


def ensure_channel(descriptor: ChannelDescriptor, tools: DelegationAgentTools) -> str:
    existing = tools.channels.search(
        ChannelSearchQuery(name=descriptor.name,
                           attributes=descriptor.attributes)
    )
    if existing:
        return existing[0].id
    channel = tools.channels.manager.create(descriptor.to_config())
    return channel.id


class BaseDelegationAgent(BaseAgent[DelegationAgentTools]):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def stop(self) -> None:
        return None

    def load(self) -> None:
        return None

    def save(self) -> None:
        return None


# ---------------------------------------------------------------------------
# エージェント実装
# ---------------------------------------------------------------------------


class HumanOperator(BaseDelegationAgent):
    """標準入力から依頼を受け付け、結果を標準出力へ表示するエージェント。"""

    def __init__(
        self,
        agent_id: str,
        channel: ChannelDescriptor,
        tasks: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(agent_id)
        self.channel_descriptor = channel
        self.initial_tasks = list(tasks or [])
        self._seeded = False
        self._manual_request_index = 1

    def run(self, tools: DelegationAgentTools) -> None:
        channel_id = ensure_channel(self.channel_descriptor, tools)
        tools.channels.join(channel_id)

        if not self._seeded:
            tasks = list(self.initial_tasks)
            if not tasks:
                tasks = self._collect_tasks_from_stdin()
            if not tasks:
                print("[Human] 入力された依頼がありません。", flush=True)
                self._seeded = True
                return
            self._seed_requests(channel_id, tools, tasks)
            self._seeded = True
            return

        self._read_responses(channel_id, tools)

    def _seed_requests(
        self,
        channel_id: str,
        tools: DelegationAgentTools,
        tasks: list[dict[str, str]],
    ) -> None:
        for task in tasks:
            prompt = task.get("prompt", "").strip()
            if not prompt:
                continue
            request_id = task.get("request_id") or self._generate_request_id()
            payload = {
                "role": "human",
                "request_id": request_id,
                "prompt": prompt,
            }
            stored = tools.channels.send(channel_id, payload)
            print(
                f"[Human] request #{stored.message_id} ({payload['request_id']}): {payload['prompt']}",
                flush=True,
            )

    def _collect_tasks_from_stdin(self) -> list[dict[str, str]]:
        print(
            "[Human] 依頼内容を1行ずつ入力してください（空行で終了）:",
            flush=True,
        )
        tasks: list[dict[str, str]] = []
        while True:
            try:
                prompt = input("> ").strip()
            except EOFError:
                break
            if not prompt:
                break
            tasks.append({"prompt": prompt})
        return tasks

    def _generate_request_id(self) -> str:
        request_id = f"input-{self._manual_request_index:03d}"
        self._manual_request_index += 1
        return request_id

    def _read_responses(self, channel_id: str, tools: DelegationAgentTools) -> None:
        received = False
        while True:
            message = tools.channels.read(channels=[channel_id])
            if message is None:
                break

            payload = message.payload
            if payload.get("role") != "assistant":
                continue

            received = True
            request_id = payload.get("request_id", "unknown")
            summary = str(payload.get("summary", "")).strip()
            conclusion = str(payload.get("conclusion", "")).strip()
            action_items = [
                str(item).strip() for item in payload.get("action_items", []) if str(item).strip()
            ]
            risks = [
                str(item).strip() for item in payload.get("risks", []) if str(item).strip()
            ]
            assumptions = [
                str(item).strip() for item in payload.get("assumptions", []) if str(item).strip()
            ]

            print(f"[Human] response for {request_id}:", flush=True)
            if summary:
                print("  概要:", flush=True)
                for line in summary.splitlines():
                    print(f"    {line}", flush=True)
            if action_items:
                print("  推奨アクション:", flush=True)
                for item in action_items:
                    print(f"    - {item}", flush=True)
            if risks:
                print("  リスク・注意点:", flush=True)
                for item in risks:
                    print(f"    - {item}", flush=True)
            if assumptions:
                print("  前提・確認事項:", flush=True)
                for item in assumptions:
                    print(f"    - {item}", flush=True)
            if conclusion:
                print(f"  結論: {conclusion}", flush=True)
            print("", flush=True)

        if not received:
            print("[Human] 未処理の応答はありません。", flush=True)


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

    def run(self, tools: DelegationAgentTools) -> None:
        human_channel_id = ensure_channel(self.human_channel_descriptor, tools)
        analysis_channel_id = ensure_channel(
            self.analysis_channel_descriptor, tools)

        tools.channels.join(human_channel_id)
        tools.channels.join(analysis_channel_id)

        self._forward_human_requests(
            tools, human_channel_id, analysis_channel_id)
        self._deliver_summaries(tools, human_channel_id, analysis_channel_id)

    def _forward_human_requests(
        self,
        tools: DelegationAgentTools,
        human_channel_id: str,
        analysis_channel_id: str,
    ) -> None:
        while True:
            message = tools.channels.read(channels=[human_channel_id])
            if message is None:
                break

            payload = message.payload
            if payload.get("role") != "human":
                continue

            request_id = payload["request_id"]
            if request_id in self.forwarded:
                continue

            prompt = payload["prompt"]
            outline = generate_analysis_outline(prompt, self.outline_model)
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
        tools: DelegationAgentTools,
        human_channel_id: str,
        analysis_channel_id: str,
    ) -> None:
        while True:
            message = tools.channels.read(channels=[analysis_channel_id])
            if message is None:
                break

            payload = message.payload
            if payload.get("role") != "analysis_summary":
                continue

            request_id = payload["request_id"]
            if request_id in self.completed:
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
            print(
                f"[FrontDesk] delivered summary for {request_id} back to human channel",
                flush=True,
            )


class AnalystAgent(BaseDelegationAgent):
    """タスク内容を分析し、要約を生成するエージェント。"""

    def __init__(self, agent_id: str, analysis_channel: ChannelDescriptor, model: str = "gpt-5-mini") -> None:
        super().__init__(agent_id)
        self.analysis_channel_descriptor = analysis_channel
        self.model = model
        self.processed: set[str] = set()

    def run(self, tools: DelegationAgentTools) -> None:
        analysis_channel_id = ensure_channel(
            self.analysis_channel_descriptor, tools)
        tools.channels.join(analysis_channel_id)

        while True:
            message = tools.channels.read(channels=[analysis_channel_id])
            if message is None:
                break

            payload = message.payload
            if payload.get("role") != "analysis_request":
                continue

            request_id = payload["request_id"]
            if request_id in self.processed:
                continue

            outline = payload.get("outline", "")
            original_prompt = payload.get("original_prompt", outline)
            result = generate_summary(original_prompt, outline, self.model)
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


class HumanOperatorConfig(AgentConfig):
    type: Literal["human_operator"] = "human_operator"
    channel: ChannelDescriptor
    tasks: list[dict[str, str]] = Field(default_factory=list)

    def build(self) -> HumanOperator:
        return HumanOperator(agent_id=self.id, channel=self.channel, tasks=self.tasks)


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
    "human_operator": HumanOperatorConfig,
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


class DelegationManager(
    StandardManager[DelegationManagerConfig,
                    DelegationManagerTools, DelegationAgentTools]
):
    def _load_tools(self) -> DelegationManagerTools:
        repository = InMemoryChannelRepository()
        manager = ChannelManager(repository)
        return DelegationManagerTools(channel_manager=manager)

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> "DelegationManager":
        config = DelegationManagerConfig(config_dir=storage_dir)
        return cls(config, delegation_adapter)


# ---------------------------------------------------------------------------
# 設定生成とデモ実行
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def prepare_configs(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

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
            "01_human_operator.json",
            {
                "type": "human_operator",
                "id": "human",
                "channel": human_channel,
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

    manager = DelegationManager.initialize_or_load(config_dir)
    agents = {agent.agent_id: agent for agent in manager.agents}

    def execute(agent_id: str) -> None:
        agent = agents[agent_id]
        tools = manager.apply_adapter(agent)
        agent.run(tools)

    execute("front_agent")
    execute("analyst_agent")
    execute("human")
    execute("front_agent")
    execute("analyst_agent")
    execute("front_agent")
    execute("human")


if __name__ == "__main__":
    run_demo()

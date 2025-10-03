from dataclasses import dataclass
from multiprocessing import Event
from pathlib import Path
from typing import Callable, Literal, Type, cast

from pydantic import BaseModel

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    ManagerExecutionBackend,
    StandardManager,
    StandardManagerConfig,
)
from nkaa.framework.persistence import JsonLinesStateMixin
from nkaa.presets.tools.llm_tool import LLMCallTool


class LogTool:
    def debug(self, message: str) -> None:
        """
        デバッグメッセージを記録する。
        Args:
            message (str): 記録するメッセージ。
        """
        print(f"DEBUG: {message}")

    def info(self, message: str) -> None:
        """
        情報レベルのメッセージを記録する。
        Args:
            message (str): 記録するメッセージ。
        """
        print(f"INFO: {message}")


class InputTool:
    def get(self) -> str:
        """
        ユーザーからの入力を取得する。
        Returns:
            str: ユーザーが提供した入力。
        """
        return "This is a placeholder input from the user."


@dataclass
class SingleAgentTools(BaseTools):
    llm_call_tool: LLMCallTool
    log_tool: LogTool
    input_tool: InputTool
    stop_tool: Callable[[], None] | None = None

    def stop(self) -> None:
        """
        エージェントのツール群を停止する。
        """
        pass

    def save(self) -> None:
        """
        エージェントのツール群の状態を保存する。
        """
        pass


class SimpleAgentConfig(AgentConfig):
    type: Literal["SingleAgent"] = "SingleAgent"
    objective: str
    model_name: str
    max_length: int
    data_root_dir: Path = Path("_data/single_agent")
    max_steps: int | None

    def build(self) -> "SingleAgent":
        return SingleAgent(config=self)


class SingleAgentMemory(BaseModel):
    content: str


class SingleAgent(JsonLinesStateMixin[SingleAgentMemory], BaseAgent[SingleAgentTools]):
    def __init__(
        self,
        config: SimpleAgentConfig,
    ):
        self.config = config
        self.memory_path = self.config.data_root_dir / "memory.jsonl"
        self.memories: list[SingleAgentMemory] = []
        self.stop_event = Event()
        self.load()

    def run(self, tools: SingleAgentTools) -> None:
        while not self.stop_event.is_set():
            input_ = tools.input_tool.get()
            prompt = f"""以下の新規情報・イベントに基づき、目的に向けた情報抽出・思考を行ってください。
# 目的
{self.config.objective}

# 新規情報・イベント
{input_}

"""
            sum_length = len(prompt)
            num_use_memories = 0
            for i in range(len(self.memories)):
                memory = self.memories[len(self.memories) - 1 - i]
                if i == 0:
                    add_prompt = "# 過去記録（以下の過去の記憶を参照してください）\n"
                    add_prompt += f"## {i + 1} 個前の記憶\n{memory.content}\n"
                else:
                    add_prompt = f"## {i + 1} 個前の記憶\n{memory.content}\n"
                sum_length += len(add_prompt)
                if sum_length > self.config.max_length:
                    break
                num_use_memories += 1
                prompt += add_prompt

            tools.log_tool.debug(f"Using {num_use_memories} memories for LLM call.\n{len(prompt)} characters.")
            response = tools.llm_call_tool.call(prompt=prompt, model_name=self.config.model_name)
            self.memories.append(SingleAgentMemory(content=response))
            if self.config.max_steps is not None and len(self.memories) >= self.config.max_steps:
                break
        if tools.stop_tool is not None:
            tools.stop_tool()

    def stop(self) -> None:
        self.stop_event.set()

    # JsonLinesStateMixin hooks -------------------------------------------------
    def get_state_path(self) -> Path:
        return self.memory_path

    def state_model_type(self) -> type[SingleAgentMemory]:
        return SingleAgentMemory

    def serialize_state(self) -> list[SingleAgentMemory]:
        return list(self.memories)

    def apply_loaded_state(self, items: list[SingleAgentMemory]) -> None:
        self.memories = list(items)


single_agent_model_agent_types = {
    "SingleAgent": SimpleAgentConfig,
}


class SingleAgentModelConfig(StandardManagerConfig):
    data_root_dir: Path = Path("_data/single_agent_model")

    def get_agent_config_paths(self) -> list[Path]:
        candidate_path = self.data_root_dir / "agent_config.json"
        return [] if not candidate_path.exists() else [candidate_path]

    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        type_ = single_agent_model_agent_types.get(type_name)
        if type_ is None:
            raise ValueError(f"Unknown agent type: {type_name}")
        return type_

    def build_tools(self) -> SingleAgentTools:
        return SingleAgentTools(
            llm_call_tool=LLMCallTool(),
            log_tool=LogTool(),
            input_tool=InputTool(),
        )


class SingleAgentModel(StandardManager[SingleAgentModelConfig, SingleAgentTools, SingleAgentTools]):
    def __init__(
        self,
        config: SingleAgentModelConfig,
        adapter: Callable[[BaseAgent[SingleAgentTools], SingleAgentTools], SingleAgentTools],
        *,
        tools: SingleAgentTools,
        execution_backend: ManagerExecutionBackend | None = None,
    ) -> None:
        super().__init__(
            config,
            adapter,
            tools=tools,
            execution_backend=execution_backend,
        )
        if self.tools.stop_tool is None:
            self.tools.stop_tool = self.create_stop_event_tool()

    @classmethod
    def initialize_or_load(
        cls,
        storage_dir: Path,
        *,
        config_factory: Callable[[Path], SingleAgentModelConfig] | None = None,
        adapter: Callable[[BaseAgent[SingleAgentTools], SingleAgentTools], SingleAgentTools] | None = None,
        tools_factory: Callable[[SingleAgentModelConfig], SingleAgentTools] | None = None,
        execution_backend: ManagerExecutionBackend | None = None,
    ) -> "SingleAgentModel":
        def default_config_factory(path: Path) -> SingleAgentModelConfig:
            return SingleAgentModelConfig(data_root_dir=path)

        resolved_config_factory = config_factory or default_config_factory
        resolved_adapter = adapter or single_agent_model_adapter

        def default_tools_factory(config: SingleAgentModelConfig) -> SingleAgentTools:
            return config.build_tools()

        resolved_tools_factory = tools_factory or default_tools_factory

        manager = super().initialize_or_load(
            storage_dir,
            config_factory=resolved_config_factory,
            adapter=resolved_adapter,
            tools_factory=resolved_tools_factory,
            execution_backend=execution_backend,
        )
        return cast("SingleAgentModel", manager)


def single_agent_model_adapter(agent: BaseAgent[SingleAgentTools], tools: SingleAgentTools) -> SingleAgentTools:
    return tools

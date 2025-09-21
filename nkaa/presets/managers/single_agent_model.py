from dataclasses import dataclass
from multiprocessing import Event
from pathlib import Path
from typing import Callable, Literal, Type

from pydantic import BaseModel

from nkaa.framework.agent import AgentConfig, BaseAgent, BaseTools, StandardManager, StandardManagerConfig
from nkaa.presets.tools.llm_tool import LLMCallTool


class LogTool:
    def debug(self, message: str) -> None:
        """
        Log a debug message.
        Args:
            message (str): The message to log.
        """
        print(f"DEBUG: {message}")

    def info(self, message: str) -> None:
        """
        Log an info message.
        Args:
            message (str): The message to log.
        """
        print(f"INFO: {message}")


class InputTool:
    def get(self) -> str:
        """
        Get input from the user.
        Returns:
            str: The input provided by the user.
        """
        return "This is a placeholder input from the user."


@dataclass
class SingleAgentTools(BaseTools):
    llm_call_tool: LLMCallTool
    log_tool: LogTool
    input_tool: InputTool
    stop_tool: Callable[[], None]

    def stop(self) -> None:
        """
        Stop the agent's tools.
        """
        pass

    def save(self) -> None:
        """
        Save the state of the agent's tools.
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


class SingleAgent(BaseAgent[SingleAgentTools]):
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
        tools.stop_tool()

    def stop(self) -> None:
        self.stop_event.set()

    def save(self) -> None:
        with self.memory_path.open("w") as f:
            for memory in self.memories:
                print(memory.model_dump_json(), file=f)

    def load(self) -> None:
        if not self.memory_path.exists():
            self.memories = []
            return
        self.memories = [
            SingleAgentMemory.model_validate_json(line) for line in self.memory_path.read_text().splitlines() if line
        ]


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


class SingleAgentModel(StandardManager[SingleAgentModelConfig, SingleAgentTools, SingleAgentTools]):
    def _load_tools(self) -> SingleAgentTools:
        return SingleAgentTools(
            llm_call_tool=LLMCallTool(),
            log_tool=LogTool(),
            input_tool=InputTool(),
            stop_tool=self.create_stop_event_tool(),
        )

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> "SingleAgentModel":
        config = SingleAgentModelConfig(data_root_dir=storage_dir)
        return cls(config, single_agent_model_adapter)


def single_agent_model_adapter(agent: BaseAgent[SingleAgentTools], tools: SingleAgentTools) -> SingleAgentTools:
    return tools

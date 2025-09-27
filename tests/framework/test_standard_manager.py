from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Literal, Type

from nkaa.framework.agent import (
    AgentConfig,
    BaseAgent,
    BaseTools,
    ManagerExecutionBackend,
    StandardManager,
    StandardManagerConfig,
    ThreadingManagerExecutionBackend,
)


class _DummyTools(BaseTools):
    def __init__(self) -> None:
        self.save_called = False
        self.stop_called = False

    def stop(self) -> None:
        self.stop_called = True

    def save(self) -> None:
        self.save_called = True


class _DummyAgent(BaseAgent[_DummyTools]):
    def __init__(self, config: "_DummyAgentConfig") -> None:
        self.config = config
        self.saved = False
        self.loaded = False
        self.stopped = False

    def run(self, tools: _DummyTools) -> None:  # pragma: no cover - テスト対象外
        raise NotImplementedError

    def stop(self) -> None:
        self.stopped = True

    def load(self) -> None:
        self.loaded = True

    def save(self) -> None:
        self.saved = True


class _DummyAgentConfig(AgentConfig):
    type: Literal["dummy"] = "dummy"

    def build(self) -> _DummyAgent:
        return _DummyAgent(config=self)


class _DummyManagerConfig(StandardManagerConfig):
    agent_paths: list[Path]

    def get_agent_config_paths(self) -> list[Path]:
        return list(self.agent_paths)

    def get_agent_config_type(self, type_name: str) -> Type[AgentConfig]:
        if type_name != "dummy":
            raise ValueError(type_name)
        return _DummyAgentConfig

    def build_tools(self) -> _DummyTools:
        return _DummyTools()


def _adapter(agent: BaseAgent[_DummyTools], tools: _DummyTools) -> _DummyTools:
    return tools


class _DummyManager(StandardManager[_DummyManagerConfig, _DummyTools, _DummyTools]):
    def __init__(
        self,
        config: _DummyManagerConfig,
        adapter: Callable[[BaseAgent[_DummyTools], _DummyTools], _DummyTools],
        *,
        tools: _DummyTools,
        execution_backend: ThreadingManagerExecutionBackend | None = None,
    ) -> None:
        super().__init__(
            config,
            adapter,
            tools=tools,
            execution_backend=execution_backend,
        )

    @classmethod
    def initialize_or_load(cls, storage_dir: Path) -> "_DummyManager":  # pragma: no cover - テスト対象外
        raise NotImplementedError


def _create_agent_config_file(path: Path) -> None:
    payload = {"type": "dummy", "id": "agent-1"}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_standard_manager_save_invokes_tool_and_agent(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.json"
    _create_agent_config_file(config_path)

    config = _DummyManagerConfig(agent_paths=[config_path])
    manager = _DummyManager(
        config,
        _adapter,
        tools=config.build_tools(),
        execution_backend=ThreadingManagerExecutionBackend(),
    )

    # load が呼ばれていることを確認
    dummy_agent = manager.agents[0]
    assert isinstance(dummy_agent, _DummyAgent)
    assert dummy_agent.loaded is True

    manager.save()

    assert manager.tools.save_called is True
    assert dummy_agent.saved is True

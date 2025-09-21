from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from nkaa.framework.agent import BaseAgent, BaseTools
from nkaa.framework.persistence import JsonLinesStateMixin


class _DummyTools(BaseTools):
    def stop(self) -> None:  # pragma: no cover - 空実装で十分
        pass

    def save(self) -> None:  # pragma: no cover - 空実装で十分
        pass


class _Memory(BaseModel):
    value: int


class _DummyAgent(JsonLinesStateMixin[_Memory], BaseAgent[_DummyTools]):
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self.values: list[_Memory] = []

    def run(self, tools: _DummyTools) -> None:  # pragma: no cover - テストでは未使用
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - テストでは未使用
        pass

    def get_state_path(self) -> Path:
        return self._state_path

    def state_model_type(self) -> type[_Memory]:
        return _Memory

    def serialize_state(self) -> Iterable[_Memory]:
        return list(self.values)

    def apply_loaded_state(self, items: list[_Memory]) -> None:
        self.values = list(items)


def test_json_lines_state_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "state.jsonl"
    agent = _DummyAgent(state_file)

    agent.load()
    assert agent.values == []

    agent.values = [_Memory(value=1), _Memory(value=2)]
    agent.save()

    reloaded = _DummyAgent(state_file)
    reloaded.load()

    assert [memory.value for memory in reloaded.values] == [1, 2]

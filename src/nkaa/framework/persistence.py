"""エージェント状態を JSON Lines 形式で永続化するためのユーティリティ。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, Iterable, Type, TypeVar

from pydantic import BaseModel

TState = TypeVar("TState", bound=BaseModel)


class JsonLinesStateMixin(ABC, Generic[TState]):
    """JSON Lines ファイルで状態を保存・復元するエージェント向け mixin。"""

    state_encoding = "utf-8"

    @abstractmethod
    def get_state_path(self) -> Path:
        """状態ファイルの保存先パスを返す。"""

    @abstractmethod
    def state_model_type(self) -> Type[TState]:
        """状態を表す Pydantic モデルの型を返す。"""

    @abstractmethod
    def serialize_state(self) -> Iterable[TState]:
        """保存対象となる状態モデルを列挙する。"""

    @abstractmethod
    def apply_loaded_state(self, items: list[TState]) -> None:
        """ロードした状態モデルを自身へ反映する。"""

    def load(self) -> None:
        """JSON Lines から状態を復元する。"""

        path = self.get_state_path()
        state_cls = self.state_model_type()
        if not path.exists():
            self.apply_loaded_state([])
            return

        raw_text = path.read_text(encoding=self.state_encoding)
        loaded: list[TState] = []
        for line in raw_text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            loaded.append(state_cls.model_validate_json(candidate))
        self.apply_loaded_state(loaded)

    def save(self) -> None:
        """現在の状態を JSON Lines ファイルへ保存する。"""

        path = self.get_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        items = list(self.serialize_state())
        lines = [item.model_dump_json() for item in items]
        content = "\n".join(lines)
        if lines:
            content += "\n"
        path.write_text(content, encoding=self.state_encoding)

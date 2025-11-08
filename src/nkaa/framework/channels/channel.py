"""チャネルの抽象化と既定実装を定義するモジュール。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field

from .models import ChannelMessage, ChannelMetadata
from .repository import ChannelRepository


class ChannelConfig(BaseModel):
    """チャネルを構築するための基本設定。"""

    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @abstractmethod
    def build(
        self,
        id_: str,
        repository: ChannelRepository,
        *,
        save_hook: Callable[[], None] | None = None,
    ) -> "BaseChannel":
        raise NotImplementedError


class BaseChannel(ABC):
    """リポジトリを介した永続化を担うチャネルの抽象クラス。"""

    def __init__(
        self,
        id_: str,
        *,
        repository: ChannelRepository,
        metadata: ChannelMetadata | None = None,
        save_hook: Callable[[], None] | None = None,
    ) -> None:
        self.id = id_
        self._repository = repository
        self._save_hook = save_hook
        if metadata is not None:
            self.metadata = metadata
        else:
            self.metadata = ChannelMetadata(id=id_, name=None, description=None)
            self._repository.register_channel(self.metadata)

    @classmethod
    def from_metadata(
        cls: "type[BaseChannelT]",
        metadata: ChannelMetadata,
        repository: ChannelRepository,
        *,
        save_hook: Callable[[], None] | None = None,
    ) -> "BaseChannelT":
        return cls(metadata.id, repository=repository, metadata=metadata, save_hook=save_hook)

    def write(self, message: ChannelMessage) -> ChannelMessage:
        if message.channel_id != self.id:
            message = message.model_copy(update={"channel_id": self.id})
        return self._repository.persist_message(message)

    def save(self) -> None:
        if self._save_hook is not None:
            self._save_hook()
            return
        self._repository.flush_channel(self.id)


BaseChannelT = TypeVar("BaseChannelT", bound=BaseChannel)


class DatabaseChannel(BaseChannel):
    """設定済みリポジトリを背後に持つチャネル（本番では PostgreSQL を想定）。"""

    def __init__(
        self,
        id_: str,
        *,
        repository: ChannelRepository,
        metadata: ChannelMetadata | None = None,
        save_hook: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(id_, repository=repository, metadata=metadata, save_hook=save_hook)


class DatabaseChannelConfig(ChannelConfig):
    """`DatabaseChannel` インスタンスを生成する既定のチャネル設定。"""

    def build(
        self,
        id_: str,
        repository: ChannelRepository,
        *,
        save_hook: Callable[[], None] | None = None,
    ) -> BaseChannel:
        metadata = ChannelMetadata(
            id=id_,
            name=self.name,
            description=self.description,
            attributes=self.attributes,
        )
        repository.register_channel(metadata)
        return DatabaseChannel(id_, repository=repository, metadata=metadata, save_hook=save_hook)

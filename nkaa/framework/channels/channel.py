"""Channel abstractions and default implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from .models import ChannelMessage, ChannelMetadata
from .repository import ChannelRepository


class ChannelConfig(BaseModel):
    """Base configuration used to build channels."""

    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @abstractmethod
    def build(self, id_: str, repository: ChannelRepository) -> "BaseChannel":
        raise NotImplementedError


class BaseChannel(ABC):
    """Abstract channel coordinating persistence via a repository."""

    def __init__(
        self,
        id_: str,
        *,
        repository: ChannelRepository,
        metadata: ChannelMetadata | None = None,
    ) -> None:
        self.id = id_
        self._repository = repository
        if metadata is not None:
            self.metadata = metadata
        else:
            self.metadata = ChannelMetadata(id=id_, name=None, description=None)
            self._repository.register_channel(self.metadata)

    @classmethod
    def from_metadata(
        cls: "type[BaseChannelT]", metadata: ChannelMetadata, repository: ChannelRepository
    ) -> "BaseChannelT":
        return cls(metadata.id, repository=repository, metadata=metadata)

    def write(self, message: ChannelMessage) -> ChannelMessage:
        if message.channel_id != self.id:
            message = message.model_copy(update={"channel_id": self.id})
        return self._repository.persist_message(message)

    def save(self) -> None:
        self._repository.flush_channel(self.id)


BaseChannelT = TypeVar("BaseChannelT", bound=BaseChannel)


class DatabaseChannel(BaseChannel):
    """Channel backed by the configured repository (PostgreSQL in production)."""

    def __init__(
        self,
        id_: str,
        *,
        repository: ChannelRepository,
        metadata: ChannelMetadata | None = None,
    ) -> None:
        super().__init__(id_, repository=repository, metadata=metadata)


class DatabaseChannelConfig(ChannelConfig):
    """Default channel configuration building `DatabaseChannel` instances."""

    def build(self, id_: str, repository: ChannelRepository) -> BaseChannel:
        metadata = ChannelMetadata(
            id=id_,
            name=self.name,
            description=self.description,
            attributes=self.attributes,
        )
        repository.register_channel(metadata)
        return DatabaseChannel(id_, repository=repository, metadata=metadata)

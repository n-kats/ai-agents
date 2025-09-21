"""Repository abstraction for channel state persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Sequence

from .models import ChannelMembership, ChannelMessage, ChannelMetadata, UnreadRecord


class ChannelRepositoryError(RuntimeError):
    """Generic persistence failure."""


class ChannelRepository(ABC):
    """Defines how channel state is persisted and retrieved."""

    @abstractmethod
    def register_channel(self, metadata: ChannelMetadata) -> None:
        """Persist a new channel's metadata."""

    @abstractmethod
    def list_channels(self) -> Sequence[ChannelMetadata]:
        """Retrieve all known channels."""

    @abstractmethod
    def persist_message(self, message: ChannelMessage) -> ChannelMessage:
        """Store a message and return the stored representation (with `message_id`)."""

    @abstractmethod
    def fetch_message(self, channel_id: str, message_id: int) -> ChannelMessage:
        """Load a single message from history."""

    @abstractmethod
    def flush_channel(self, channel_id: str) -> None:
        """Complete any pending writes for a channel."""

    @abstractmethod
    def replace_unread_records(self, records: Sequence[UnreadRecord]) -> None:
        """Persist a full snapshot of unread records across all agents."""

    @abstractmethod
    def load_unread_records(self) -> Sequence[UnreadRecord]:
        """Load unread snapshot from persistence."""

    @abstractmethod
    def record_membership(self, membership: ChannelMembership) -> None:
        """Persist the fact that an agent participates in a channel."""

    @abstractmethod
    def remove_membership(self, membership: ChannelMembership) -> None:
        """Remove persisted channel participation information."""

    @abstractmethod
    def load_memberships(self) -> Sequence[ChannelMembership]:
        """Load channel memberships for all agents."""


class InMemoryChannelRepository(ChannelRepository):
    """Fallback repository used for tests and development."""

    def __init__(self) -> None:
        self._channels: dict[str, ChannelMetadata] = {}
        self._messages: dict[str, list[ChannelMessage]] = defaultdict(list)
        self._memberships: set[tuple[str, str]] = set()
        self._unread_records: list[UnreadRecord] = []
        self._message_counters: dict[str, int] = defaultdict(int)

    def register_channel(self, metadata: ChannelMetadata) -> None:
        self._channels[metadata.id] = metadata

    def list_channels(self) -> Sequence[ChannelMetadata]:
        return list(self._channels.values())

    def persist_message(self, message: ChannelMessage) -> ChannelMessage:
        counter = self._message_counters[message.channel_id] + 1
        self._message_counters[message.channel_id] = counter
        stored = message.model_copy(update={"message_id": counter})
        self._messages[stored.channel_id].append(stored)
        return stored

    def fetch_message(self, channel_id: str, message_id: int) -> ChannelMessage:
        for message in self._messages[channel_id]:
            if message.message_id == message_id:
                return message
        raise ChannelRepositoryError(f"Message {message_id} not found in channel {channel_id}")

    def flush_channel(self, channel_id: str) -> None:
        # In-memory implementation has nothing to flush.
        return None

    def replace_unread_records(self, records: Sequence[UnreadRecord]) -> None:
        self._unread_records = list(records)

    def load_unread_records(self) -> Sequence[UnreadRecord]:
        return list(self._unread_records)

    def record_membership(self, membership: ChannelMembership) -> None:
        self._memberships.add((membership.channel_id, membership.agent_id))

    def remove_membership(self, membership: ChannelMembership) -> None:
        self._memberships.discard((membership.channel_id, membership.agent_id))

    def load_memberships(self) -> Sequence[ChannelMembership]:
        return [
            ChannelMembership(channel_id=channel_id, agent_id=agent_id)
            for channel_id, agent_id in sorted(self._memberships)
        ]

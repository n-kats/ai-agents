"""Channel manager coordinating channel lifecycle and agent delivery."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from .channel import BaseChannel, ChannelConfig, DatabaseChannel
from .models import ChannelMembership, ChannelMessage, UnreadRecord
from .queue import AgentMessagePointer, MessageQueue
from .repository import ChannelRepository, ChannelRepositoryError


class ChannelManager:
    """Manage channels, memberships, and unread pointers for agents."""

    def __init__(self, repository: ChannelRepository) -> None:
        self.repository = repository
        self.channels: dict[str, BaseChannel] = {}
        self._memberships: dict[str, set[str]] = defaultdict(set)
        self._agent_queues: dict[str, MessageQueue] = {}
        self._next_index = 1

        self._restore_channels()
        self._restore_memberships()
        self._restore_unread()

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------
    def new_id(self) -> str:
        next_id = f"channel_{self._next_index}"
        self._next_index += 1
        return next_id

    def register(self, channel: BaseChannel) -> BaseChannel:
        self.channels[channel.id] = channel
        self._sync_counter(channel.id)
        return channel

    def create(self, config: ChannelConfig, *, channel_cls: type[BaseChannel] | None = None) -> BaseChannel:
        channel_id = self.new_id()
        channel = config.build(channel_id, repository=self.repository)
        if channel_cls is not None and not isinstance(channel, channel_cls):
            channel = channel_cls(channel_id, repository=self.repository, metadata=channel.metadata)
        return self.register(channel)

    def find(self, id_: str) -> BaseChannel:
        try:
            return self.channels[id_]
        except KeyError as exc:
            raise KeyError(f"Channel '{id_}' not found") from exc

    def list_channels(self) -> Mapping[str, BaseChannel]:
        return dict(self.channels)

    def save(self) -> None:
        for channel in self.channels.values():
            channel.save()

        unread_records: list[UnreadRecord] = []
        for agent_id, queue in self._agent_queues.items():
            for pointer in queue.snapshot():
                unread_records.append(
                    UnreadRecord(
                        agent_id=agent_id,
                        channel_id=pointer.channel_id,
                        message_id=pointer.message_id,
                        priority=pointer.priority,
                        enqueued_at=pointer.enqueued_at,
                    )
                )

        self.repository.replace_unread_records(unread_records)

    # ------------------------------------------------------------------
    # Membership management
    # ------------------------------------------------------------------
    def ensure_agent_registered(self, agent_id: str) -> None:
        self._agent_queues.setdefault(agent_id, MessageQueue())

    def join_agent(self, channel_id: str, agent_id: str) -> None:
        self.ensure_agent_registered(agent_id)
        self._memberships[channel_id].add(agent_id)
        self.repository.record_membership(ChannelMembership(channel_id=channel_id, agent_id=agent_id))

    def leave_agent(self, channel_id: str, agent_id: str) -> None:
        agents = self._memberships.get(channel_id)
        if agents and agent_id in agents:
            agents.remove(agent_id)
            self.repository.remove_membership(ChannelMembership(channel_id=channel_id, agent_id=agent_id))
        queue = self._agent_queues.get(agent_id)
        if queue is not None:
            queue.discard([channel_id])

    def channels_for_agent(self, agent_id: str) -> list[str]:
        return [channel_id for channel_id, members in self._memberships.items() if agent_id in members]

    # ------------------------------------------------------------------
    # Message delivery
    # ------------------------------------------------------------------
    def write(self, channel_id: str, message: ChannelMessage) -> ChannelMessage:
        channel = self.find(channel_id)
        stored = channel.write(message)
        recipients = self._memberships.get(channel_id, set())
        if stored.message_id is None:
            raise ChannelRepositoryError("Repository did not return a message_id for stored message")
        pointer = AgentMessagePointer(
            channel_id=channel_id,
            message_id=stored.message_id,
            priority=stored.priority,
        )
        for agent_id in recipients:
            queue = self._agent_queues.setdefault(agent_id, MessageQueue())
            queue.put(pointer)
        return stored

    def read_for_agent(
        self,
        agent_id: str,
        *,
        block: bool = False,
        timeout: float | None = None,
        allowed_channels: Iterable[str] | None = None,
    ) -> ChannelMessage | None:
        queue = self._agent_queues.get(agent_id)
        if queue is None:
            return None

        allowed = list(allowed_channels) if allowed_channels is not None else None
        pointer = queue.get(block=block, timeout=timeout, allowed_channels=allowed)
        if pointer is None:
            return None
        return self.repository.fetch_message(pointer.channel_id, pointer.message_id)

    # ------------------------------------------------------------------
    # Restoration helpers
    # ------------------------------------------------------------------
    def _restore_channels(self) -> None:
        for metadata in self.repository.list_channels():
            channel = DatabaseChannel.from_metadata(metadata, repository=self.repository)
            self.register(channel)

    def _restore_memberships(self) -> None:
        for membership in self.repository.load_memberships():
            self._memberships[membership.channel_id].add(membership.agent_id)
            self.ensure_agent_registered(membership.agent_id)

    def _restore_unread(self) -> None:
        for record in self.repository.load_unread_records():
            queue = self._agent_queues.setdefault(record.agent_id, MessageQueue())
            queue.put(
                AgentMessagePointer(
                    channel_id=record.channel_id,
                    message_id=record.message_id,
                    priority=record.priority,
                    enqueued_at=record.enqueued_at,
                )
            )

    def _sync_counter(self, channel_id: str) -> None:
        prefix = "channel_"
        if channel_id.startswith(prefix):
            suffix = channel_id[len(prefix) :]
            if suffix.isdigit():
                self._next_index = max(self._next_index, int(suffix) + 1)

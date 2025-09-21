from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from nkaa.framework.agent import BaseTools
from nkaa.framework.channel import BaseChannel, BaseMessage, ChannelManager


@dataclass
class ChannelAccess:
    """Wrapper exposing read/write operations for a single channel."""

    channel: BaseChannel

    def read(self) -> BaseMessage | None:
        return self.channel.read()

    def write(self, message: BaseMessage) -> None:
        self.channel.write(message)

    def id(self) -> str:
        return self.channel.id


@dataclass
class ChannelTools(BaseTools):
    """Collection of channel accessors provided to an agent."""

    channels: Mapping[str, ChannelAccess]
    manager: ChannelManager

    def stop(self) -> None:
        # No-op for in-memory channels by default.
        return None

    def save(self) -> None:
        for accessor in self.channels.values():
            accessor.channel.save()

    def get(self, channel_id: str) -> ChannelAccess:
        return self.channels[channel_id]

    def values(self) -> Sequence[ChannelAccess]:
        return list(self.channels.values())

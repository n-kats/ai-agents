"""Channel framework primitives exposed for public use."""

from .channel import BaseChannel, ChannelConfig, ChannelMetadata, DatabaseChannel, DatabaseChannelConfig
from .manager import ChannelManager
from .models import ChannelMessage, UnreadRecord
from .queue import AgentMessagePointer, MessageQueue
from .repository import ChannelRepository, InMemoryChannelRepository

__all__ = [
    "AgentMessagePointer",
    "BaseChannel",
    "ChannelConfig",
    "ChannelManager",
    "ChannelMessage",
    "ChannelMetadata",
    "ChannelRepository",
    "DatabaseChannel",
    "DatabaseChannelConfig",
    "InMemoryChannelRepository",
    "MessageQueue",
    "UnreadRecord",
]

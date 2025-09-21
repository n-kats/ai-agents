"""公開APIとして提供するチャネルフレームワークのプリミティブ。"""

from .channel import BaseChannel, ChannelConfig, ChannelMetadata, DatabaseChannel, DatabaseChannelConfig
from .manager import ChannelManager
from .models import ChannelMessage, ChannelSearchQuery, UnreadRecord
from .queue import AgentMessagePointer, MessageQueue
from .repository import ChannelRepository, InMemoryChannelRepository, SQLChannelRepository

__all__ = [
    "AgentMessagePointer",
    "BaseChannel",
    "ChannelConfig",
    "ChannelManager",
    "ChannelMessage",
    "ChannelSearchQuery",
    "ChannelMetadata",
    "ChannelRepository",
    "DatabaseChannel",
    "DatabaseChannelConfig",
    "InMemoryChannelRepository",
    "SQLChannelRepository",
    "MessageQueue",
    "UnreadRecord",
]

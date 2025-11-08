"""チャネルマネージャーをメッセージルート抽象へ適合させるアダプター。"""

from __future__ import annotations

from typing import Iterable

from nkaa.framework.message_manager import MessageRouteProvider

from .channel import BaseChannel
from .manager import ChannelManager


class ChannelMessageRouteProvider(MessageRouteProvider):
    """ChannelManager を MessageManager 用のルート解決抽象として利用する。"""

    def __init__(self, channel_manager: ChannelManager) -> None:
        self._channel_manager = channel_manager

    def resolve_destination(self, destination_id: str) -> BaseChannel:
        return self._channel_manager.find(destination_id)

    def recipients_for(self, destination_id: str) -> Iterable[str]:
        return self._channel_manager.members_for_channel(destination_id)

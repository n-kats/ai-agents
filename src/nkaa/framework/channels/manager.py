"""チャネルのライフサイクルとエージェントへの配送を調整するチャネルマネージャー。"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Protocol, Sequence

from .channel import BaseChannel, ChannelConfig, DatabaseChannel
from .models import ChannelMembership, ChannelMetadata, ChannelSearchQuery
from .repository import ChannelRepository


class UnreadQueueHandler(Protocol):
    """離脱時に未読ポインタを破棄するためのハンドラ抽象。"""

    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None: ...


class ChannelManager:
    """チャネル、メンバーシップ、未読ポインタを管理するクラス。"""

    def __init__(self, repository: ChannelRepository) -> None:
        self.repository = repository
        self.channels: dict[str, BaseChannel] = {}
        self._memberships: dict[str, set[str]] = defaultdict(set)
        self._known_agents: set[str] = set()
        self._unread_handler: UnreadQueueHandler | None = None
        self._next_index = 1

        self._restore_channels()
        self._restore_memberships()

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

        def save_hook(channel_id: str = channel_id) -> None:
            self.repository.flush_channel(channel_id)

        channel = config.build(
            channel_id,
            repository=self.repository,
            save_hook=save_hook,
        )
        if channel_cls is not None and not isinstance(channel, channel_cls):
            channel = channel_cls(
                channel_id,
                repository=self.repository,
                metadata=channel.metadata,
                save_hook=save_hook,
            )
        return self.register(channel)

    def find(self, id_: str) -> BaseChannel:
        try:
            return self.channels[id_]
        except KeyError as exc:
            raise KeyError(f"Channel '{id_}' not found") from exc

    def list_channels(self) -> Mapping[str, BaseChannel]:
        return dict(self.channels)

    def search_channels(self, query: ChannelSearchQuery | None = None) -> list[ChannelMetadata]:
        """チャネルメタデータを検索条件と照合して返す。"""

        if query is None:
            return [self.channels[channel_id].metadata for channel_id in sorted(self.channels)]

        results: list[ChannelMetadata] = []
        for channel_id in sorted(self.channels):
            metadata = self.channels[channel_id].metadata
            if query.matches(metadata):
                results.append(metadata)
                if query.limit is not None and len(results) >= query.limit:
                    break
        return results

    # ------------------------------------------------------------------
    # Membership management
    # ------------------------------------------------------------------
    def ensure_agent_registered(self, agent_id: str) -> None:
        self._known_agents.add(agent_id)

    def join_agent(self, channel_id: str, agent_id: str) -> None:
        self.ensure_agent_registered(agent_id)
        self._memberships[channel_id].add(agent_id)
        self.repository.record_membership(ChannelMembership(channel_id=channel_id, agent_id=agent_id))

    def leave_agent(self, channel_id: str, agent_id: str) -> None:
        agents = self._memberships.get(channel_id)
        if agents and agent_id in agents:
            agents.remove(agent_id)
            self.repository.remove_membership(ChannelMembership(channel_id=channel_id, agent_id=agent_id))
        if self._unread_handler is not None:
            self._unread_handler.discard_agent_channels(agent_id, [channel_id])

    def channels_for_agent(self, agent_id: str) -> list[str]:
        return [channel_id for channel_id, members in self._memberships.items() if agent_id in members]

    def members_for_channel(self, channel_id: str) -> Sequence[str]:
        """指定チャネルに参加しているエージェントIDを昇順で返す。"""

        return tuple(sorted(self._memberships.get(channel_id, set())))

    # ------------------------------------------------------------------
    # Restoration helpers
    # ------------------------------------------------------------------
    def _restore_channels(self) -> None:
        for metadata in self.repository.list_channels():
            channel_id = metadata.id

            def save_hook(channel_id: str = channel_id) -> None:
                self.repository.flush_channel(channel_id)

            channel = DatabaseChannel.from_metadata(
                metadata,
                repository=self.repository,
                save_hook=save_hook,
            )
            self.register(channel)

    def _restore_memberships(self) -> None:
        for membership in self.repository.load_memberships():
            self._memberships[membership.channel_id].add(membership.agent_id)
            self._known_agents.add(membership.agent_id)

    def _sync_counter(self, channel_id: str) -> None:
        prefix = "channel_"
        if channel_id.startswith(prefix):
            suffix = channel_id[len(prefix) :]
            if suffix.isdigit():
                self._next_index = max(self._next_index, int(suffix) + 1)

    # ------------------------------------------------------------------
    # Integration hooks
    # ------------------------------------------------------------------
    def attach_unread_handler(self, handler: UnreadQueueHandler) -> None:
        """未読ポインタ破棄用ハンドラを登録する。"""

        self._unread_handler = handler

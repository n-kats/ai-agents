from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from nkaa.framework.agent import BaseTools
from nkaa.framework.channels.manager import ChannelManager
from nkaa.framework.channels.models import ChannelMessage, ChannelMetadata, ChannelSearchQuery, UnreadRecord
from nkaa.framework.messages import StopMessage


@dataclass
class ChannelTools(BaseTools):
    """マネージャー経由でチャネルとやり取りするためのエージェント向けインターフェース。"""

    agent_id: str
    manager: ChannelManager
    default_priority: int = 0

    def __post_init__(self) -> None:
        self.manager.ensure_agent_registered(self.agent_id)

    # ------------------------------------------------------------------
    # Lifecycle hooks required by BaseTools
    # ------------------------------------------------------------------
    def stop(self) -> None:
        return None

    def save(self) -> None:
        """担当エージェントの未読キューをスナップショットとして永続化する。"""

        current_records = self.manager.snapshot_unread_records(self.agent_id)
        existing_records = self.manager.repository.load_unread_records()
        persisted_records = [record for record in existing_records if record.agent_id != self.agent_id]
        if current_records:
            persisted_records.extend(current_records)
        self.manager.repository.replace_unread_records(persisted_records)

    def save_channel(self, channel_id: str) -> None:
        """指定したチャネルの保存処理を実行する。"""

        channel = self.manager.find(channel_id)
        channel.save()

    # ------------------------------------------------------------------
    # Channel membership helpers
    # ------------------------------------------------------------------
    def join(self, channel_id: str) -> None:
        self.manager.join_agent(channel_id, self.agent_id)

    def leave(self, channel_id: str) -> None:
        self.manager.leave_agent(channel_id, self.agent_id)

    def join_matching(self, query: ChannelSearchQuery, *, limit: int | None = None) -> Sequence[str]:
        """検索条件に合致するチャネルへ自動参加するユーティリティ。"""

        joined = set(self.joined_channels())
        newly_joined: list[str] = []
        for metadata in self.manager.search_channels(query):
            channel_id = metadata.id
            if channel_id in joined:
                continue
            self.join(channel_id)
            joined.add(channel_id)
            newly_joined.append(channel_id)
            if limit is not None and len(newly_joined) >= limit:
                break
        return tuple(newly_joined)

    def joined_channels(self) -> Sequence[str]:
        return tuple(sorted(self.manager.channels_for_agent(self.agent_id)))

    def joined_channel_metadata(self) -> Sequence[ChannelMetadata]:
        joined = set(self.manager.channels_for_agent(self.agent_id))
        return tuple(
            channel.metadata for channel_id, channel in self.manager.list_channels().items() if channel_id in joined
        )

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------
    def send(
        self,
        channel_id: str,
        payload: Any,
        *,
        priority: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMessage:
        message = ChannelMessage(
            channel_id=channel_id,
            sender_id=self.agent_id,
            payload=payload,
            priority=self.default_priority if priority is None else priority,
            metadata=metadata or {},
        )
        return self.manager.write(channel_id, message)

    async def send_async(
        self,
        channel_id: str,
        payload: Any,
        *,
        priority: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMessage:
        """非同期にメッセージを書き込む。"""

        return await asyncio.to_thread(
            self.send,
            channel_id,
            payload,
            priority=priority,
            metadata=metadata,
        )

    def read(
        self,
        *,
        block: bool = False,
    ) -> ChannelMessage | None:
        return self.manager.read_for_agent(
            self.agent_id,
            block=block,
        )

    async def read_async(
        self,
        *,
        poll_interval: float = 0.5,
        stop_event: asyncio.Event | None = None,
        allowed_channels: Sequence[str] | None = None,
    ) -> ChannelMessage | StopMessage | None:
        """非同期に未読メッセージを取得する。"""

        while True:
            if stop_event is not None and stop_event.is_set():
                return StopMessage(reason="stop_event_set")
            message = await asyncio.to_thread(
                self.manager.read_for_agent,
                self.agent_id,
                block=True,
                timeout=poll_interval,
                allowed_channels=allowed_channels,
            )
            if message is not None:
                return message
            if stop_event is not None and stop_event.is_set():
                return StopMessage(reason="stop_event_set")
            await asyncio.sleep(0)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def list_channels(self) -> Sequence[tuple[str, ChannelMetadata]]:
        return tuple((channel_id, channel.metadata) for channel_id, channel in self.manager.list_channels().items())

    def search(self, query: ChannelSearchQuery | None = None) -> Sequence[ChannelMetadata]:
        """チャネルメタデータを条件指定で取得する。"""

        return tuple(self.manager.search_channels(query))

    def get_channel_name(self, channel_id: str) -> str:
        """チャンネルIDから表示用名称を取得する（未登録ならIDを返す）。"""

        try:
            metadata = self.manager.find(channel_id).metadata
        except KeyError:
            return channel_id
        return metadata.name or channel_id

    def snapshot_unread(self) -> list[UnreadRecord]:
        """エージェント自身の未読情報スナップショットを取得する。"""

        return self.manager.snapshot_unread_records(self.agent_id)

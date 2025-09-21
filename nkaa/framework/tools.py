from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from nkaa.framework.agent import BaseTools
from nkaa.framework.channels.manager import ChannelManager
from nkaa.framework.channels.models import ChannelMessage, ChannelMetadata, UnreadRecord


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

    def joined_channels(self) -> Sequence[str]:
        return tuple(sorted(self.manager.channels_for_agent(self.agent_id)))

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

    def read(
        self,
        *,
        block: bool = False,
        timeout: float | None = None,
        channels: Iterable[str] | None = None,
    ) -> ChannelMessage | None:
        return self.manager.read_for_agent(
            self.agent_id,
            block=block,
            timeout=timeout,
            allowed_channels=channels,
        )

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def list_channels(self) -> Sequence[tuple[str, ChannelMetadata]]:
        return tuple((channel_id, channel.metadata) for channel_id, channel in self.manager.list_channels().items())

    def snapshot_unread(self) -> list[UnreadRecord]:
        """エージェント自身の未読情報スナップショットを取得する。"""

        return self.manager.snapshot_unread_records(self.agent_id)

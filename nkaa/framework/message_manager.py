"""メッセージ配送と未読キュー管理を担当するマネージャ。"""

from __future__ import annotations

from typing import Iterable, Protocol

from nkaa.framework.channels.models import ChannelMessage, UnreadRecord
from nkaa.framework.channels.queue import AgentMessagePointer, MessageQueue
from nkaa.framework.channels.repository import ChannelRepository, ChannelRepositoryError


class MessageSink(Protocol):
    """書き込み操作のみを必要とする送信先の抽象。"""

    def write(self, message: ChannelMessage) -> ChannelMessage:
        """メッセージを保存し、保存済み表現を返す。"""


class MessageRouteProvider(Protocol):
    """メッセージ送信先と受信者を解決するための抽象。"""

    def resolve_destination(self, destination_id: str) -> MessageSink:
        """送信先 ID から書き込み可能なエンドポイントを取得する。"""

    def recipients_for(self, destination_id: str) -> Iterable[str]:
        """送信先に紐づく受信エージェント ID を列挙する。"""


class MessageManager:
    """チャネルを跨いだメッセージ配送と未読状態を制御する。"""

    def __init__(self, repository: ChannelRepository, route_provider: MessageRouteProvider) -> None:
        self.repository = repository
        self._route_provider = route_provider
        self._agent_queues: dict[str, MessageQueue] = {}
        self._restore_unread()

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def ensure_agent_registered(self, agent_id: str) -> None:
        """エージェント用の未読キューを初期化する。"""

        self._agent_queues.setdefault(agent_id, MessageQueue())

    # ------------------------------------------------------------------
    # Message delivery
    # ------------------------------------------------------------------
    def write(self, destination_id: str, message: ChannelMessage) -> ChannelMessage:
        sink = self._route_provider.resolve_destination(destination_id)
        stored = sink.write(message)
        recipients = self._route_provider.recipients_for(destination_id)
        if stored.message_id is None:
            raise ChannelRepositoryError("Repository did not return a message_id for stored message")
        pointer = AgentMessagePointer(
            channel_id=destination_id,
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
    # Snapshot helpers
    # ------------------------------------------------------------------
    def snapshot_unread_records(self, agent_id: str | None = None) -> list[UnreadRecord]:
        """未読キューのスナップショットを取得する。"""

        records: list[UnreadRecord] = []
        targets = {agent_id} if agent_id is not None else None
        for current_agent, queue in self._agent_queues.items():
            if targets is not None and current_agent not in targets:
                continue
            for pointer in queue.snapshot():
                records.append(
                    UnreadRecord(
                        agent_id=current_agent,
                        channel_id=pointer.channel_id,
                        message_id=pointer.message_id,
                        priority=pointer.priority,
                        enqueued_at=pointer.enqueued_at,
                    )
                )
        return records

    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None:
        """エージェントの未読キューから指定チャネルのポインタを削除する。"""

        queue = self._agent_queues.get(agent_id)
        if queue is None:
            return
        queue.discard(channel_ids)

    # ------------------------------------------------------------------
    # Restoration helpers
    # ------------------------------------------------------------------
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

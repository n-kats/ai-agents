"""メッセージ配送と未読キュー管理を担当するマネージャ。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
import time
from threading import Condition
from typing import Iterable, Protocol, Sequence

from sqlalchemy import MetaData, Table, delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nkaa.framework.channels.models import ChannelMessage, UnreadRecord
from nkaa.framework.channels.queue import AgentMessagePointer, MessageQueue
from nkaa.framework.channels.repository import (
    ChannelRepository,
    ChannelRepositoryError,
    SQLChannelRepository,
)


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


class MessageQueueBackend(ABC):
    """未読メッセージを保持・取得するバックエンドの抽象。"""

    @property
    @abstractmethod
    def is_persistent(self) -> bool:
        """キューが DB などの永続層に直接保管される場合は True。"""

    @abstractmethod
    def ensure_agent_registered(self, agent_id: str) -> None:
        """必要に応じてエージェント専用の内部状態を作成する。"""

    @abstractmethod
    def enqueue_for_agents(self, agent_ids: Iterable[str], pointer: AgentMessagePointer) -> None:
        """指定したエージェント全員の未読キューへポインタを投入する。"""

    @abstractmethod
    def dequeue_for_agent(
        self,
        agent_id: str,
        *,
        allowed_channels: Iterable[str] | None = None,
    ) -> AgentMessagePointer | None:
        """エージェントの未読キューから最優先のポインタを取り出す（存在しない場合は None）。"""

    @abstractmethod
    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None:
        """エージェントの未読キューから指定チャネルのポインタを削除する。"""

    @abstractmethod
    def snapshot(self, agent_id: str | None = None) -> list[UnreadRecord]:
        """未読キューの現在の内容をレコードとして取得する。"""


class InMemoryMessageQueueBackend(MessageQueueBackend):
    """従来どおりのインメモリ優先度キュー実装。"""

    def __init__(self, records: Sequence[UnreadRecord] | None = None) -> None:
        self._queues: dict[str, MessageQueue] = {}
        if records:
            for record in records:
                queue = self._queues.setdefault(record.agent_id, MessageQueue())
                queue.put(
                    AgentMessagePointer(
                        channel_id=record.channel_id,
                        message_id=record.message_id,
                        priority=record.priority,
                        enqueued_at=record.enqueued_at,
                    )
                )

    @property
    def is_persistent(self) -> bool:
        return False

    def ensure_agent_registered(self, agent_id: str) -> None:
        self._queues.setdefault(agent_id, MessageQueue())

    def enqueue_for_agents(self, agent_ids: Iterable[str], pointer: AgentMessagePointer) -> None:
        for agent_id in agent_ids:
            queue = self._queues.setdefault(agent_id, MessageQueue())
            queue.put(pointer)

    def dequeue_for_agent(
        self,
        agent_id: str,
        *,
        allowed_channels: Iterable[str] | None = None,
    ) -> AgentMessagePointer | None:
        queue = self._queues.get(agent_id)
        if queue is None:
            return None
        allowed = tuple(allowed_channels) if allowed_channels is not None else None
        return queue.get(block=False, timeout=None, allowed_channels=allowed)

    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None:
        queue = self._queues.get(agent_id)
        if queue is None:
            return
        queue.discard(channel_ids)

    def snapshot(self, agent_id: str | None = None) -> list[UnreadRecord]:
        records: list[UnreadRecord] = []
        targets = {agent_id} if agent_id is not None else None
        for current_agent, queue in self._queues.items():
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


class SQLMessageQueueBackend(MessageQueueBackend):
    """channel_unread テーブルを直接利用するバックエンド。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        metadata = MetaData()
        self._unread_table = Table("channel_unread", metadata, autoload_with=engine)
        self._supports_for_update = engine.dialect.name not in ("sqlite", "duckdb")

    @property
    def is_persistent(self) -> bool:
        return True

    def ensure_agent_registered(self, agent_id: str) -> None:
        return None

    def enqueue_for_agents(self, agent_ids: Iterable[str], pointer: AgentMessagePointer) -> None:
        rows: list[dict[str, object]] = []
        for agent_id in agent_ids:
            rows.append(
                {
                    "agent_id": agent_id,
                    "channel_id": pointer.channel_id,
                    "message_id": pointer.message_id,
                    "priority": pointer.priority,
                    "enqueued_at": pointer.enqueued_at,
                }
            )
        if not rows:
            return
        with self._engine.begin() as connection:
            connection.execute(insert(self._unread_table), rows)

    def dequeue_for_agent(
        self,
        agent_id: str,
        *,
        allowed_channels: Iterable[str] | None = None,
    ) -> AgentMessagePointer | None:
        allowed = tuple(allowed_channels) if allowed_channels is not None else None
        if allowed is not None and len(allowed) == 0:
            return None

        with Session(self._engine) as session:
            stmt = (
                select(self._unread_table)
                .where(self._unread_table.c.agent_id == agent_id)
                .order_by(
                    self._unread_table.c.priority.asc(),
                    self._unread_table.c.enqueued_at.asc(),
                    self._unread_table.c.id.asc(),
                )
                .limit(1)
            )
            if allowed is not None:
                stmt = stmt.where(self._unread_table.c.channel_id.in_(allowed))
            if self._supports_for_update:
                stmt = stmt.with_for_update(skip_locked=True)
            row = session.execute(stmt).first()
            if row is None:
                return None
            record_id = row._mapping[self._unread_table.c.id]
            pointer = AgentMessagePointer(
                channel_id=row._mapping[self._unread_table.c.channel_id],
                message_id=row._mapping[self._unread_table.c.message_id],
                priority=row._mapping[self._unread_table.c.priority],
                enqueued_at=row._mapping[self._unread_table.c.enqueued_at],
            )
            session.execute(delete(self._unread_table).where(self._unread_table.c.id == record_id))
            session.commit()
            return pointer

    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None:
        ids = tuple(channel_ids)
        if not ids:
            return
        with self._engine.begin() as connection:
            connection.execute(
                delete(self._unread_table).where(
                    (self._unread_table.c.agent_id == agent_id) & (self._unread_table.c.channel_id.in_(ids))
                )
            )

    def snapshot(self, agent_id: str | None = None) -> list[UnreadRecord]:
        with Session(self._engine) as session:
            stmt = select(self._unread_table)
            if agent_id is not None:
                stmt = stmt.where(self._unread_table.c.agent_id == agent_id)
            stmt = stmt.order_by(
                self._unread_table.c.agent_id,
                self._unread_table.c.priority.asc(),
                self._unread_table.c.enqueued_at.asc(),
                self._unread_table.c.id.asc(),
            )
            rows = session.execute(stmt).all()
            return [
                UnreadRecord(
                    agent_id=row._mapping[self._unread_table.c.agent_id],
                    channel_id=row._mapping[self._unread_table.c.channel_id],
                    message_id=row._mapping[self._unread_table.c.message_id],
                    priority=row._mapping[self._unread_table.c.priority],
                    enqueued_at=row._mapping[self._unread_table.c.enqueued_at],
                )
                for row in rows
            ]


class MessageManager:
    """チャネルを跨いだメッセージ配送と未読状態を制御する。"""

    _poll_interval: float = 0.1

    def __init__(
        self,
        repository: ChannelRepository,
        route_provider: MessageRouteProvider,
        *,
        queue_backend: MessageQueueBackend | None = None,
    ) -> None:
        self.repository = repository
        self._route_provider = route_provider
        self._queue_backend = queue_backend or self._default_backend_for(repository)
        self._agent_conditions: dict[str, Condition] = defaultdict(Condition)

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def ensure_agent_registered(self, agent_id: str) -> None:
        """エージェント用の未読キューを初期化する。"""

        self._queue_backend.ensure_agent_registered(agent_id)
        self._agent_conditions.setdefault(agent_id, Condition())

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
        self._queue_backend.enqueue_for_agents(recipients, pointer)
        self._notify_agents(recipients)
        return stored

    def read_for_agent(
        self,
        agent_id: str,
        *,
        block: bool = False,
        timeout: float | None = None,
        allowed_channels: Iterable[str] | None = None,
    ) -> ChannelMessage | None:
        allowed = tuple(allowed_channels) if allowed_channels is not None else None
        pointer = self._queue_backend.dequeue_for_agent(agent_id, allowed_channels=allowed)
        if pointer is not None:
            return self.repository.fetch_message(pointer.channel_id, pointer.message_id)

        if not block:
            return None

        deadline = None if timeout is None else time.monotonic() + timeout
        condition = self._agent_conditions.setdefault(agent_id, Condition())

        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return None
            wait_time = (
                self._poll_interval
                if remaining is None
                else max(0.0, min(self._poll_interval, remaining))
            )
            with condition:
                condition.wait(timeout=wait_time)
            pointer = self._queue_backend.dequeue_for_agent(agent_id, allowed_channels=allowed)
            if pointer is not None:
                return self.repository.fetch_message(pointer.channel_id, pointer.message_id)

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------
    def snapshot_unread_records(self, agent_id: str | None = None) -> list[UnreadRecord]:
        """未読キューのスナップショットを取得する。"""

        return self._queue_backend.snapshot(agent_id)

    def discard_agent_channels(self, agent_id: str, channel_ids: Iterable[str]) -> None:
        """エージェントの未読キューから指定チャネルのポインタを削除する。"""

        self._queue_backend.discard_agent_channels(agent_id, channel_ids)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _notify_agents(self, agent_ids: Iterable[str]) -> None:
        for agent_id in agent_ids:
            condition = self._agent_conditions.setdefault(agent_id, Condition())
            with condition:
                condition.notify_all()

    def _default_backend_for(self, repository: ChannelRepository) -> MessageQueueBackend:
        if isinstance(repository, SQLChannelRepository):
            return SQLMessageQueueBackend(repository.engine)
        return InMemoryMessageQueueBackend(repository.load_unread_records())

    @property
    def queue_is_persistent(self) -> bool:
        return self._queue_backend.is_persistent

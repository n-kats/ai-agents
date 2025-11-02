"""チャネル状態の永続化を担うリポジトリアブストラクション。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import JSON, DateTime, Index, Integer, String, create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import ChannelMembership, ChannelMessage, ChannelMetadata, UnreadRecord


class ChannelRepositoryError(RuntimeError):
    """永続化処理に関する一般的な失敗を表す例外。"""


class ChannelRepository(ABC):
    """チャネル状態の永続化と取得方法を定義する抽象クラス。"""

    @abstractmethod
    def register_channel(self, metadata: ChannelMetadata) -> None:
        """新しいチャネルのメタデータを永続化する。"""

    @abstractmethod
    def list_channels(self) -> Sequence[ChannelMetadata]:
        """既知のチャネルをすべて取得する。"""

    @abstractmethod
    def persist_message(self, message: ChannelMessage) -> ChannelMessage:
        """メッセージを保存し、`message_id` を含む保存済みの表現を返す。"""

    @abstractmethod
    def fetch_message(self, channel_id: str, message_id: int) -> ChannelMessage:
        """履歴から単一のメッセージを読み込む。"""

    @abstractmethod
    def iter_channel_messages(self, channel_id: str) -> Sequence[ChannelMessage]:
        """チャネルに保存されたメッセージを作成順に走査する。"""

    @abstractmethod
    def flush_channel(self, channel_id: str) -> None:
        """チャネルに対して保留中の書き込みをすべて確定させる。"""

    @abstractmethod
    def replace_unread_records(self, records: Sequence[UnreadRecord]) -> None:
        """全エージェント分の未読レコードをスナップショットとして保存し直す。"""

    @abstractmethod
    def load_unread_records(self) -> Sequence[UnreadRecord]:
        """永続化済みの未読スナップショットを読み込む。"""

    @abstractmethod
    def record_membership(self, membership: ChannelMembership) -> None:
        """エージェントがチャネルに参加している情報を保存する。"""

    @abstractmethod
    def remove_membership(self, membership: ChannelMembership) -> None:
        """保存済みのチャネル参加情報を削除する。"""

    @abstractmethod
    def load_memberships(self) -> Sequence[ChannelMembership]:
        """すべてのエージェント分のチャネル参加情報を読み込む。"""


class InMemoryChannelRepository(ChannelRepository):
    """テストや開発向けのフォールバックリポジトリ。"""

    def __init__(self) -> None:
        self._channels: dict[str, ChannelMetadata] = {}
        self._messages: dict[str, list[ChannelMessage]] = defaultdict(list)
        self._memberships: set[tuple[str, str]] = set()
        self._unread_records: list[UnreadRecord] = []
        self._message_counters: dict[str, int] = defaultdict(int)

    def register_channel(self, metadata: ChannelMetadata) -> None:
        self._channels[metadata.id] = metadata

    def list_channels(self) -> Sequence[ChannelMetadata]:
        return list(self._channels.values())

    def persist_message(self, message: ChannelMessage) -> ChannelMessage:
        counter = self._message_counters[message.channel_id] + 1
        self._message_counters[message.channel_id] = counter
        stored = message.model_copy(update={"message_id": counter})
        self._messages[stored.channel_id].append(stored)
        return stored

    def fetch_message(self, channel_id: str, message_id: int) -> ChannelMessage:
        for message in self._messages[channel_id]:
            if message.message_id == message_id:
                return message
        raise ChannelRepositoryError(f"Message {message_id} not found in channel {channel_id}")

    def iter_channel_messages(self, channel_id: str) -> Sequence[ChannelMessage]:
        return list(self._messages.get(channel_id, []))

    def flush_channel(self, channel_id: str) -> None:
        # In-memory implementation has nothing to flush.
        return None

    def replace_unread_records(self, records: Sequence[UnreadRecord]) -> None:
        self._unread_records = list(records)

    def load_unread_records(self) -> Sequence[UnreadRecord]:
        return list(self._unread_records)

    def record_membership(self, membership: ChannelMembership) -> None:
        self._memberships.add((membership.channel_id, membership.agent_id))

    def remove_membership(self, membership: ChannelMembership) -> None:
        self._memberships.discard((membership.channel_id, membership.agent_id))

    def load_memberships(self) -> Sequence[ChannelMembership]:
        return [
            ChannelMembership(channel_id=channel_id, agent_id=agent_id)
            for channel_id, agent_id in sorted(self._memberships)
        ]


class _SQLBase(DeclarativeBase):
    """チャネルリポジトリ用テーブルを束ねる SQLAlchemy のベースクラス。"""


class _ChannelRow(_SQLBase):
    __tablename__ = "channel_channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _MessageRow(_SQLBase):
    __tablename__ = "channel_messages"

    channel_id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _MembershipRow(_SQLBase):
    __tablename__ = "channel_memberships"

    channel_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, primary_key=True)


class _UnreadRow(_SQLBase):
    __tablename__ = "channel_unread"
    __table_args__ = (
        Index(
            "ix_channel_unread_agent_priority_enqueued_id",
            "agent_id",
            "priority",
            "enqueued_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SQLChannelRepository(ChannelRepository):
    """SQLAlchemy を利用してチャネル状態を永続化するリポジトリ実装。"""

    def __init__(self, engine: Engine, *, create_tables: bool = True) -> None:
        self.engine = engine
        if create_tables:
            _SQLBase.metadata.create_all(engine)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        create_tables: bool = True,
        **create_engine_kwargs: Any,
    ) -> "SQLChannelRepository":
        """接続URLからエンジンを生成してリポジトリを構築するヘルパー。"""

        engine = create_engine(url, future=True, **create_engine_kwargs)
        return cls(engine, create_tables=create_tables)

    def register_channel(self, metadata: ChannelMetadata) -> None:
        with Session(self.engine) as session:
            row = session.get(_ChannelRow, metadata.id)
            if row is None:
                session.add(
                    _ChannelRow(
                        id=metadata.id,
                        name=metadata.name,
                        description=metadata.description,
                        created_at=metadata.created_at,
                        attributes=dict(metadata.attributes or {}),
                    )
                )
            else:
                row.name = metadata.name
                row.description = metadata.description
                row.created_at = metadata.created_at
                row.attributes = dict(metadata.attributes or {})
            session.commit()

    def list_channels(self) -> Sequence[ChannelMetadata]:
        with Session(self.engine) as session:
            rows = session.execute(select(_ChannelRow).order_by(_ChannelRow.id)).scalars().all()
        return [
            ChannelMetadata(
                id=row.id,
                name=row.name,
                description=row.description,
                created_at=row.created_at,
                attributes=dict(row.attributes or {}),
            )
            for row in rows
        ]

    def persist_message(self, message: ChannelMessage) -> ChannelMessage:
        with Session(self.engine) as session:
            next_id = session.execute(
                select(func.coalesce(func.max(_MessageRow.message_id), 0) + 1).where(
                    _MessageRow.channel_id == message.channel_id
                )
            ).scalar_one()
            stored = message.model_copy(update={"message_id": int(next_id)})
            session.add(
                _MessageRow(
                    channel_id=stored.channel_id,
                    message_id=stored.message_id,
                    sender_id=stored.sender_id,
                    payload=stored.payload,
                    priority=stored.priority,
                    created_at=stored.created_at,
                    metadata_json=dict(stored.metadata or {}),
                )
            )
            session.commit()
        return stored

    def fetch_message(self, channel_id: str, message_id: int) -> ChannelMessage:
        with Session(self.engine) as session:
            row = session.get(_MessageRow, (channel_id, message_id))
            if row is None:
                raise ChannelRepositoryError(f"Message {message_id} not found in channel {channel_id}")
            return ChannelMessage(
                channel_id=row.channel_id,
                sender_id=row.sender_id,
                payload=row.payload,
                priority=row.priority,
                created_at=row.created_at,
                metadata=dict(row.metadata_json or {}),
                message_id=row.message_id,
            )

    def iter_channel_messages(self, channel_id: str) -> Sequence[ChannelMessage]:
        with Session(self.engine) as session:
            rows = (
                session.execute(
                    select(_MessageRow)
                    .where(_MessageRow.channel_id == channel_id)
                    .order_by(_MessageRow.message_id.asc())
                )
                .scalars()
                .all()
            )
        return [
            ChannelMessage(
                channel_id=row.channel_id,
                sender_id=row.sender_id,
                payload=row.payload,
                priority=row.priority,
                created_at=row.created_at,
                metadata=dict(row.metadata_json or {}),
                message_id=row.message_id,
            )
            for row in rows
        ]

    def flush_channel(self, channel_id: str) -> None:
        # SQLAlchemy のセッション境界ごとに commit 済みなので追加処理は不要。
        return None

    def replace_unread_records(self, records: Sequence[UnreadRecord]) -> None:
        with Session(self.engine) as session:
            session.execute(delete(_UnreadRow))
            for record in records:
                session.add(
                    _UnreadRow(
                        agent_id=record.agent_id,
                        channel_id=record.channel_id,
                        message_id=record.message_id,
                        priority=record.priority,
                        enqueued_at=record.enqueued_at,
                    )
                )
            session.commit()

    def load_unread_records(self) -> Sequence[UnreadRecord]:
        with Session(self.engine) as session:
            rows = session.execute(select(_UnreadRow).order_by(_UnreadRow.id)).scalars().all()
        return [
            UnreadRecord(
                agent_id=row.agent_id,
                channel_id=row.channel_id,
                message_id=row.message_id,
                priority=row.priority,
                enqueued_at=row.enqueued_at,
            )
            for row in rows
        ]

    def record_membership(self, membership: ChannelMembership) -> None:
        with Session(self.engine) as session:
            session.merge(_MembershipRow(channel_id=membership.channel_id, agent_id=membership.agent_id))
            session.commit()

    def remove_membership(self, membership: ChannelMembership) -> None:
        with Session(self.engine) as session:
            session.execute(
                delete(_MembershipRow).where(
                    _MembershipRow.channel_id == membership.channel_id,
                    _MembershipRow.agent_id == membership.agent_id,
                )
            )
            session.commit()

    def load_memberships(self) -> Sequence[ChannelMembership]:
        with Session(self.engine) as session:
            rows = (
                session.execute(select(_MembershipRow).order_by(_MembershipRow.channel_id, _MembershipRow.agent_id))
                .scalars()
                .all()
            )
        return [ChannelMembership(channel_id=row.channel_id, agent_id=row.agent_id) for row in rows]

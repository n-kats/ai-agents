"""チャネル関連の各種プリミティブで共有されるデータモデル。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """タイムゾーン情報を含むUTCタイムスタンプを返す。"""

    return datetime.now(UTC)


class ChannelMetadata(BaseModel):
    """リポジトリに保持されるチャネルの軽量なメタデータ。"""

    id: str
    name: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ChannelMessage(BaseModel):
    """チャネル履歴として保存される構造化メッセージ。"""

    channel_id: str
    sender_id: str
    payload: Any
    priority: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    message_id: int | None = None


class ChannelMembership(BaseModel):
    """特定のチャネルに参加するエージェントを表す。"""

    channel_id: str
    agent_id: str


class UnreadRecord(BaseModel):
    """エージェント向けの未読メッセージを表すレコード。"""

    agent_id: str
    channel_id: str
    message_id: int
    priority: int
    enqueued_at: datetime = Field(default_factory=_utcnow)

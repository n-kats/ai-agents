"""チャネル関連の各種プリミティブで共有されるデータモデル。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _casefold(text: str | None) -> str | None:
    """Casefold helper for optional strings."""

    return text.casefold() if text is not None else None


class ChannelSearchQuery(BaseModel):
    """チャネルメタデータを条件付きで取得するための検索条件。"""

    channel_ids: set[str] = Field(default_factory=set)
    name: str | None = None
    name_contains: str | None = None
    description_contains: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = None

    def matches(self, metadata: "ChannelMetadata") -> bool:
        """メタデータが検索条件に合致するかを評価する。"""

        if self.channel_ids and metadata.id not in self.channel_ids:
            return False

        if self.name is not None:
            if metadata.name != self.name:
                return False

        if self.name_contains is not None:
            needle = self.name_contains.casefold()
            haystack = _casefold(metadata.name)
            if haystack is None or needle not in haystack:
                return False

        if self.description_contains is not None:
            needle = self.description_contains.casefold()
            haystack = _casefold(metadata.description)
            if haystack is None or needle not in haystack:
                return False

        if self.attributes:
            metadata_attributes = metadata.attributes or {}
            for key, expected in self.attributes.items():
                if metadata_attributes.get(key) != expected:
                    return False

        return True


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

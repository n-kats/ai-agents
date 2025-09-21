"""Data models shared across channel primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class ChannelMetadata(BaseModel):
    """Lightweight description of a channel preserved in the repository."""

    id: str
    name: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ChannelMessage(BaseModel):
    """Structured message persisted for channel history."""

    channel_id: str
    sender_id: str
    payload: Any
    priority: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    message_id: int | None = None


class ChannelMembership(BaseModel):
    """Agent participating in a specific channel."""

    channel_id: str
    agent_id: str


class UnreadRecord(BaseModel):
    """Record describing an unread message entry for an agent."""

    agent_id: str
    channel_id: str
    message_id: int
    priority: int
    enqueued_at: datetime = Field(default_factory=_utcnow)

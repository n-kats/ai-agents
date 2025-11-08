"""エージェント専用メッセージキューを管理するユーティリティ。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, PriorityQueue
from typing import Iterable, Sequence


def _utcnow() -> datetime:
    """タイムゾーン情報を含むUTCタイムスタンプを返す。"""

    return datetime.now(UTC)


@dataclass(frozen=True)
class AgentMessagePointer:
    """リポジトリに保存されたメッセージを特定のエージェント向けに指し示すポインタ。"""

    channel_id: str
    message_id: int
    priority: int = 0
    enqueued_at: datetime = field(default_factory=_utcnow)


class _QueueEntry:
    __slots__ = ("_priority", "_enqueued_at", "pointer")

    def __init__(self, pointer: AgentMessagePointer):
        self.pointer = pointer
        self._priority = pointer.priority
        self._enqueued_at = pointer.enqueued_at

    def __lt__(self, other: "_QueueEntry") -> bool:
        if self._priority != other._priority:
            return self._priority < other._priority
        return self._enqueued_at < other._enqueued_at


class MessageQueue:
    """メッセージポインタを決定的な順序で扱う優先度付きキュー。"""

    def __init__(self) -> None:
        self._queue: PriorityQueue[_QueueEntry] = PriorityQueue()

    def put(self, pointer: AgentMessagePointer) -> None:
        self._queue.put(_QueueEntry(pointer))

    def get(
        self,
        *,
        block: bool = False,
        timeout: float | None = None,
        allowed_channels: Sequence[str] | None = None,
    ) -> AgentMessagePointer | None:
        allowed = set(allowed_channels) if allowed_channels is not None else None
        stash: list[_QueueEntry] = []
        while True:
            try:
                entry = self._queue.get(block=block, timeout=timeout)
            except Empty:
                for queued in stash:
                    self._queue.put(queued)
                return None

            pointer = entry.pointer
            if allowed is None or pointer.channel_id in allowed:
                for queued in stash:
                    self._queue.put(queued)
                return pointer

            stash.append(entry)
            block = False
            timeout = 0

    def empty(self) -> bool:
        return self._queue.empty()

    def discard(self, channel_ids: Iterable[str]) -> None:
        targets = set(channel_ids)
        if not targets:
            return
        retained: list[_QueueEntry] = []
        while True:
            try:
                entry = self._queue.get_nowait()
            except Empty:
                break
            if entry.pointer.channel_id not in targets:
                retained.append(entry)
        for entry in retained:
            self._queue.put(entry)

    def snapshot(self) -> list[AgentMessagePointer]:
        retained: list[_QueueEntry] = []
        pointers: list[AgentMessagePointer] = []
        while True:
            try:
                entry = self._queue.get_nowait()
            except Empty:
                break
            retained.append(entry)
            pointers.append(entry.pointer)
        for entry in retained:
            self._queue.put(entry)
        return pointers

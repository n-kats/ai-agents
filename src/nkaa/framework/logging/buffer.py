from __future__ import annotations

import threading
import weakref
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, Dict, Iterable, Literal

from loguru import logger

__all__ = [
    "LogRecord",
    "LogRecordEvent",
    "LogStream",
    "Subscription",
    "LogBufferSink",
    "ensure_buffer_sink_attached",
    "get_log_stream",
    "reset_buffer_sink_attachment",
]


@dataclass(frozen=True, slots=True)
class LogRecord:
    """構造化されたログレコード。"""

    message: str
    level: str
    level_no: int
    timestamp: datetime
    module: str
    function: str
    line: int
    context: Dict[str, Any]
    extra: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class LogRecordEvent:
    """ログストリーム購読者へ送るイベント。"""

    kind: Literal["record", "reset"]
    record: LogRecord | None = None


class Subscription:
    """ログ購読の寿命を管理するハンドル。"""

    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._lock = threading.Lock()
        self._active = True

    def unsubscribe(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
        self._cancel()


class LogStream:
    """リングバッファからログを購読するためのストリーム。"""

    def __init__(
        self,
        sink: "LogBufferSink",
        *,
        level: str | None = None,
        context_filters: Dict[str, Any] | None = None,
    ) -> None:
        self._sink_ref = weakref.ref(sink)
        self._level = level
        self._context_filters = context_filters or {}
        self._subscribers: Dict[int, Callable[[LogRecordEvent], None]] = {}
        self._next_token = 0
        self._lock = threading.RLock()
        sink._register_stream(self)

    def snapshot(self, limit: int | None = None) -> list[LogRecord]:
        sink = self._sink_ref()
        if sink is None:
            return []
        records = sink._copy_buffer()
        filtered = [record for record in records if self._matches(record)]
        if limit is None:
            return filtered
        return filtered[-limit:]

    def subscribe(self, callback: Callable[[LogRecordEvent], None]) -> Subscription:
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = callback

        def _cancel() -> None:
            with self._lock:
                self._subscribers.pop(token, None)

        return Subscription(_cancel)

    def set_filters(self, level: str | None = None, **context_filters: Any) -> None:
        with self._lock:
            if level is not None:
                self._level = level
            if context_filters:
                self._context_filters = context_filters
            elif level is None and not context_filters:
                self._level = None
                self._context_filters = {}
        self._notify_reset()

    def clear_filters(self) -> None:
        with self._lock:
            self._level = None
            self._context_filters = {}
        self._notify_reset()

    def close(self) -> None:
        sink = self._sink_ref()
        if sink is None:
            return
        sink._unregister_stream(self)

    # ------------------------------------------------------------------
    # 内部ヘルパー（LogBufferSink から呼び出される）
    # ------------------------------------------------------------------
    def _notify_record(self, record: LogRecord) -> None:
        if not self._matches(record):
            return
        event = LogRecordEvent(kind="record", record=record)
        for callback in self._iter_subscribers():
            callback(event)

    def _notify_reset(self) -> None:
        event = LogRecordEvent(kind="reset", record=None)
        for callback in self._iter_subscribers():
            callback(event)

    def _iter_subscribers(self) -> Iterable[Callable[[LogRecordEvent], None]]:
        with self._lock:
            callbacks = list(self._subscribers.values())
        return callbacks

    def _matches(self, record: LogRecord) -> bool:
        if self._level is not None:
            required = logger.level(self._level).no
            if record.level_no < required:
                return False
        if not self._context_filters:
            return True
        for key, expected in self._context_filters.items():
            if record.context.get(key) != expected:
                return False
        return True


class LogBufferSink:
    """loguru シンクとして機能するリングバッファ。"""

    def __init__(self, limit: int = 500) -> None:
        self._buffer: Deque[LogRecord] = deque(maxlen=limit)
        self._lock = threading.RLock()
        self._streams: "weakref.WeakSet[LogStream]" = weakref.WeakSet()
        self._limit = limit

    # loguru から呼び出される
    def __call__(self, message: Any) -> None:  # pragma: no cover - loguru 実行時に呼び出される
        record = self._build_record(message)
        with self._lock:
            self._buffer.append(record)
            streams = list(self._streams)
        for stream in streams:
            stream._notify_record(record)

    def _register_stream(self, stream: LogStream) -> None:
        with self._lock:
            self._streams.add(stream)

    def _unregister_stream(self, stream: LogStream) -> None:
        with self._lock:
            try:
                self._streams.remove(stream)
            except KeyError:
                pass

    def _copy_buffer(self) -> list[LogRecord]:
        with self._lock:
            return list(self._buffer)

    def set_limit(self, limit: int) -> None:
        with self._lock:
            if limit == self._limit:
                return
            records = list(self._buffer)
            self._buffer = deque(records[-limit:], maxlen=limit)
            self._limit = limit
            streams = list(self._streams)
        for stream in streams:
            stream._notify_reset()

    def get_limit(self) -> int:
        return self._limit

    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ------------------------------------------------------------------
    # レコード変換
    # ------------------------------------------------------------------
    def _build_record(self, message: Any) -> LogRecord:
        record = message.record
        extra = dict(record.get("extra", {}))
        context = _extract_context(extra)
        time_value = record.get("time")
        timestamp = time_value if isinstance(time_value, datetime) else datetime.fromtimestamp(time_value.timestamp())
        level_name, level_no = _parse_level(record.get("level"))
        return LogRecord(
            message=record.get("message", ""),
            level=level_name,
            level_no=level_no,
            timestamp=timestamp,
            module=record.get("module", ""),
            function=record.get("function", ""),
            line=record.get("line", 0),
            context=context,
            extra=extra,
        )


_RESERVED_EXTRA_KEYS = {
    "exception",
    "file",
    "function",
    "module",
    "line",
    "name",
    "process",
    "thread",
}


def _extract_context(extra: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in extra.items() if key not in _RESERVED_EXTRA_KEYS and not key.startswith("_")}


def _parse_level(level_obj: Any) -> tuple[str, int]:
    if isinstance(level_obj, dict):
        name = str(level_obj.get("name", ""))
        no = level_obj.get("no")
        return name, int(no or 0)
    name = getattr(level_obj, "name", None)
    no = getattr(level_obj, "no", None)
    if name is None:
        name = str(level_obj)
    if no is None:
        try:
            no = logger.level(name).no
        except (TypeError, ValueError):  # pragma: no cover - 未定義レベル
            no = 0
    return str(name), int(no)


_BUFFER_SINK: LogBufferSink | None = None
_BUFFER_ATTACHED = False
_BUFFER_HANDLE: int | None = None


def _ensure_buffer_sink() -> LogBufferSink:
    global _BUFFER_SINK
    if _BUFFER_SINK is None:
        _BUFFER_SINK = LogBufferSink()
    return _BUFFER_SINK


def ensure_buffer_sink_attached(*, level: str = "TRACE") -> tuple[LogBufferSink, int]:
    sink = _ensure_buffer_sink()
    global _BUFFER_ATTACHED, _BUFFER_HANDLE
    if not _BUFFER_ATTACHED:
        _BUFFER_HANDLE = logger.add(sink, level=level, enqueue=False)
        _BUFFER_ATTACHED = True
    if _BUFFER_HANDLE is None:
        _BUFFER_HANDLE = logger.add(sink, level=level, enqueue=False)
    return sink, _BUFFER_HANDLE


def reset_buffer_sink_attachment() -> None:
    global _BUFFER_ATTACHED, _BUFFER_HANDLE
    _BUFFER_ATTACHED = False
    _BUFFER_HANDLE = None


def get_log_stream(*, level: str | None = None, **context_filters: Any) -> LogStream:
    """既定のリングバッファからストリームを作成する。"""

    sink, _ = ensure_buffer_sink_attached()
    return LogStream(sink, level=level, context_filters=context_filters or None)

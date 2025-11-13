from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from .buffer import (
    ensure_buffer_sink_attached,
    get_log_stream,
    reset_buffer_sink_attachment,
)

__all__ = [
    "LoggingState",
    "configure_logging",
    "get_logging_state",
    "get_log_stream",
    "set_global_log_level",
    "set_sink_level",
]


@dataclass(slots=True)
class SinkState:
    name: str
    sink_type: str
    level: str
    destination: str | None
    enabled: bool
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BufferState:
    limit: int
    size: int


@dataclass(slots=True)
class LoggingState:
    global_level: str | None
    sinks: list[SinkState]
    buffer: BufferState


@dataclass(slots=True)
class _SinkConfig:
    name: str
    level: str
    sink_type: str
    destination: str | None
    id: int
    options: Dict[str, Any]


_CONFIG_LOCK = threading.RLock()
_GLOBAL_LEVEL: str | None = None
_SINK_CONFIGS: Dict[str, _SinkConfig] = {}


def configure_logging(
    *,
    enable_console: bool = False,
    log_file: str | Path | None = None,
    json_file: str | Path | None = None,
    buffer_limit: int = 500,
) -> LoggingState:
    """loguru のシンクをシンプルに構成する。"""

    with _CONFIG_LOCK:
        logger.remove()
        reset_buffer_sink_attachment()

        buffer_sink, sink_id = ensure_buffer_sink_attached()
        buffer_sink.set_limit(buffer_limit)
        _SINK_CONFIGS.clear()
        global _GLOBAL_LEVEL
        _GLOBAL_LEVEL = None
        _SINK_CONFIGS["buffer"] = _SinkConfig(
            name="buffer",
            level="TRACE",
            sink_type="buffer",
            destination=None,
            id=sink_id,
            options={"limit": buffer_limit},
        )

        if enable_console:
            _SINK_CONFIGS["console"] = _add_console_sink()

        if log_file is not None:
            _SINK_CONFIGS["file"] = _add_file_sink(Path(log_file))

        if json_file is not None:
            _SINK_CONFIGS["json"] = _add_json_sink(Path(json_file))

        return _compose_state_locked()


def get_logging_state() -> LoggingState:
    with _CONFIG_LOCK:
        return _compose_state_locked()


def set_global_log_level(level: str | None) -> LoggingState:
    with _CONFIG_LOCK:
        global _GLOBAL_LEVEL
        _GLOBAL_LEVEL = level
        return _compose_state_locked()


def set_sink_level(name: str, level: str) -> LoggingState:
    with _CONFIG_LOCK:
        config = _SINK_CONFIGS.get(name)
        if config is None:
            raise KeyError(f"Sink '{name}' is not registered")
        config.level = level
        return _compose_state_locked()


def _compose_state_locked() -> LoggingState:
    buffer_sink, _ = ensure_buffer_sink_attached()
    buffer_state = BufferState(limit=buffer_sink.get_limit(), size=buffer_sink.size())
    sinks = [
        SinkState(
            name=config.name,
            sink_type=config.sink_type,
            level=config.level,
            destination=config.destination,
            enabled=True,
            options=dict(config.options),
        )
        for config in _SINK_CONFIGS.values()
    ]
    sinks.sort(key=lambda state: state.name)
    return LoggingState(global_level=_GLOBAL_LEVEL, sinks=sinks, buffer=buffer_state)


def _add_console_sink() -> _SinkConfig:
    config = _SinkConfig(
        name="console",
        level="INFO",
        sink_type="console",
        destination=None,
        id=-1,
        options={},
    )
    sink_id = logger.add(
        sys.stderr,
        level="TRACE",
        filter=lambda record, cfg=config: _allow_record(cfg, record),
        enqueue=False,
    )
    config.id = sink_id
    return config


def _add_file_sink(path: Path) -> _SinkConfig:
    path.parent.mkdir(parents=True, exist_ok=True)
    config = _SinkConfig(
        name="file",
        level="DEBUG",
        sink_type="file",
        destination=str(path),
        id=-1,
        options={"rotation": "10 MB"},
    )
    sink_id = logger.add(
        str(path),
        level="TRACE",
        rotation="10 MB",
        filter=lambda record, cfg=config: _allow_record(cfg, record),
        enqueue=False,
    )
    config.id = sink_id
    return config


def _add_json_sink(path: Path) -> _SinkConfig:
    path.parent.mkdir(parents=True, exist_ok=True)
    config = _SinkConfig(
        name="json",
        level="INFO",
        sink_type="json",
        destination=str(path),
        id=-1,
        options={"serialize": True},
    )
    sink_id = logger.add(
        str(path),
        level="TRACE",
        serialize=True,
        filter=lambda record, cfg=config: _allow_record(cfg, record),
        enqueue=False,
    )
    config.id = sink_id
    return config


def _allow_record(config: _SinkConfig, record: Dict[str, Any]) -> bool:
    with _CONFIG_LOCK:
        level_name = config.level
        global_level = _GLOBAL_LEVEL

    level_no = logger.level(level_name).no
    record_level = record.get("level")
    _, record_level_no = _parse_record_level(record_level)
    if record_level_no < level_no:
        return False

    if global_level is not None and record_level_no < logger.level(global_level).no:
        return False

    return True


def _parse_record_level(level_obj: Any) -> tuple[str, int]:
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

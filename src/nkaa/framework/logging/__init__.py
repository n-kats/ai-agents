"""Logging utilities built around loguru for NKAA framework."""

from __future__ import annotations

from .agent_tool import AgentLogTool
from .buffer import LogRecord, LogRecordEvent, LogStream, get_log_stream
from .config import (
    LoggingState,
    configure_logging,
    get_logging_state,
    set_global_log_level,
    set_sink_level,
)
from .panel_adapter import LogPanelAdapter

__all__ = [
    "AgentLogTool",
    "LogPanelAdapter",
    "LogRecord",
    "LogRecordEvent",
    "LogStream",
    "LoggingState",
    "configure_logging",
    "get_log_stream",
    "get_logging_state",
    "set_global_log_level",
    "set_sink_level",
]

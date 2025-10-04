from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger

from .buffer import LogStream, get_log_stream
from .config import LoggingState, get_logging_state

__all__ = ["AgentLogTool"]


class AgentLogTool:
    """エージェント向けに提供するログツール。"""

    def __init__(self, *, agent_id: str) -> None:
        self._agent_id = agent_id
        self._logger = logger.bind(agent_id=agent_id)

    @property
    def logger(self) -> Logger:
        return self._logger

    @contextmanager
    def context(self, **metadata: Any) -> Iterator[None]:
        with self._logger.contextualize(**metadata):
            yield

    def get_stream(
        self,
        *,
        level: str | None = None,
        include_agent_context: bool = True,
        **filters: Any,
    ) -> LogStream:
        """リングバッファを購読するストリームを取得する。

        include_agent_context が True の場合は agent_id を自動付与し、
        False なら呼び出し側のフィルタ指定をそのまま利用する。
        """

        if include_agent_context:
            filters.setdefault("agent_id", self._agent_id)
        return get_log_stream(level=level, **filters)

    def get_logging_state(self) -> LoggingState:
        return get_logging_state()

from __future__ import annotations

import threading
from typing import Any, Callable

from .buffer import LogRecord, LogRecordEvent, LogStream, Subscription

__all__ = ["LogPanelAdapter"]


Formatter = Callable[[LogRecord], str]


class LogPanelAdapter:
    """Textual などの CUI ログパネルとリングバッファを仲介するアダプター。"""

    def __init__(
        self,
        log_stream: LogStream,
        *,
        widget_factory: Callable[[], Any],
        level: str | None = None,
        formatter: Formatter | None = None,
        follow_tail: bool = True,
    ) -> None:
        self._log_stream = log_stream
        self._widget_factory = widget_factory
        self._formatter = formatter or self._default_formatter
        self._follow_tail = follow_tail
        self._widget: Any | None = None
        self._app: Any | None = None
        self._subscription: Subscription | None = None
        self._lock = threading.RLock()
        self._level = level
        self._context_filters: dict[str, Any] = {}

    def install(self, app: Any) -> Any:
        """Textual アプリから呼び出し、表示ウィジェットを生成する。"""

        self._app = app
        self._widget = self._widget_factory()
        return self._widget

    def start(self) -> None:
        """購読を開始し、初期スナップショットを描画する。"""

        with self._lock:
            if self._subscription is not None:
                return
            if self._level is not None or self._context_filters:
                self._log_stream.set_filters(level=self._level, **self._context_filters)
            self._subscription = self._log_stream.subscribe(self._handle_event)
        self.refresh_from_snapshot()

    def stop(self) -> None:
        with self._lock:
            if self._subscription is not None:
                self._subscription.unsubscribe()
                self._subscription = None

    def set_level(self, level: str | None) -> None:
        with self._lock:
            self._level = level
            self._log_stream.set_filters(level=level, **self._context_filters)
        self.refresh_from_snapshot()

    def set_filters(self, **context_filters: Any) -> None:
        with self._lock:
            self._context_filters = context_filters
            self._log_stream.set_filters(level=self._level, **self._context_filters)
        self.refresh_from_snapshot()

    def clear_filters(self) -> None:
        with self._lock:
            self._context_filters = {}
            self._level = None
            self._log_stream.clear_filters()
        self.refresh_from_snapshot()

    def refresh_from_snapshot(self) -> None:
        records = self._log_stream.snapshot()
        self._run_in_app_thread(self._render_snapshot, records)

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------
    def _handle_event(self, event: LogRecordEvent) -> None:
        if event.kind == "reset":
            self.refresh_from_snapshot()
            return
        if event.record is None:
            return
        rendered = self._formatter(event.record)
        self._run_in_app_thread(self._append_line, rendered)

    def _run_in_app_thread(self, func: Callable[..., None], *args: Any) -> None:
        widget = self._widget
        if widget is None:
            return
        app = self._app
        if app is not None and hasattr(app, "call_from_thread"):
            app_thread_id = getattr(app, "_thread_id", None)
            current_thread_id = threading.get_ident()
            try:
                if app_thread_id is None or app_thread_id != current_thread_id:
                    app.call_from_thread(func, *args)
                    return
            except RuntimeError:
                # Textual が未起動の場合などはフォールバック
                pass
        func(*args)

    def _append_line(self, line: str) -> None:
        widget = self._widget
        if widget is None:
            return
        if not line.endswith("\n"):
            line = f"{line}\n"
        if hasattr(widget, "write"):
            widget.write(line)
        elif hasattr(widget, "add_text"):
            widget.add_text(line)
        if self._follow_tail and hasattr(widget, "scroll_end"):
            widget.scroll_end(animate=False)

    def _render_snapshot(self, records: list[LogRecord]) -> None:
        widget = self._widget
        if widget is None:
            return
        if hasattr(widget, "clear"):
            widget.clear()
        for record in records:
            self._append_line(self._formatter(record))

    @staticmethod
    def _default_formatter(record: LogRecord) -> str:
        context = " ".join(f"{key}={value}" for key, value in sorted(record.context.items()))
        context_part = f" [{context}]" if context else ""
        timestamp = record.timestamp.strftime("%H:%M:%S")
        return f"[{timestamp}] <{record.level}> {record.message}{context_part}"

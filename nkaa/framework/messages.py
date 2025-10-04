"""フレームワーク全体で利用する共通メッセージオブジェクト。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopMessage:
    """協調停止を伝えるためのメッセージ。"""

    reason: str | None = None

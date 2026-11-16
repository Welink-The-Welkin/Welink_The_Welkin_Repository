"""时间源抽象，为状态时间字段提供 now()。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """默认时间源，返回带 UTC 时区的当前时间。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
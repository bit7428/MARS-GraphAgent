"""可注入的时钟与 id 生成器，保证测试可复现。"""

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """时间来源。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        ...

    def monotonic(self) -> float:
        """返回单调递增秒数，用于耗时统计。"""
        ...


class SystemClock:
    """生产时钟。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """返回单调秒数。"""
        return time.monotonic()


class IdGenerator(Protocol):
    """运行级 id 生成器。"""

    def new_id(self, prefix: str) -> str:
        """生成带前缀的新 id。"""
        ...


class SequentialIdGenerator:
    """进程内递增 id，避免 uuid4 导致不可复现。"""

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self, prefix: str) -> str:
        """生成带前缀的新 id。"""
        self._counter += 1
        return f"{prefix}-{self._counter:06d}"

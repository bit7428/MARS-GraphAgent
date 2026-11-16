"""自定义 reducer。"""

from typing import Any


def append_trace(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """trace 通道按执行顺序追加，不做去重。"""
    return [*(left or []), *(right or [])]

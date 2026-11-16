"""可复现的元素 id 生成。"""

import re

_ID_PATTERN = re.compile(r"^(?P<prefix>[a-z]+)(?P<number>\d+)$")


def next_id(prefix: str, existing: list[str] | tuple[str, ...]) -> str:
    """按已有 id 的最大序号生成下一个 id，禁止使用 uuid4。"""
    highest = 0
    for item in existing:
        match = _ID_PATTERN.match(item)
        if match and match.group("prefix") == prefix:
            highest = max(highest, int(match.group("number")))
    return f"{prefix}{highest + 1:03d}"

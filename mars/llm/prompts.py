"""提示词文件加载；代码中只保留版本号。"""

import re
from functools import lru_cache
from pathlib import Path

from mars.graph.state.errors import MarsError

_PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_VERSION_PATTERN = re.compile(r"^v\d+$")


class PromptNotFoundError(MarsError):
    """提示词版本不存在。"""


@lru_cache(maxsize=64)
def load_prompt(node: str, version: str) -> str:
    """读取 prompts/<node>/<version>.md；空文件合法。"""
    if not _VERSION_PATTERN.match(version):
        raise PromptNotFoundError(f"非法提示词版本: {version}")
    path = _PROMPT_ROOT / node / f"{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"提示词不存在: {node}/{version}")
    return path.read_text(encoding="utf-8")

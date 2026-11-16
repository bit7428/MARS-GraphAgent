"""提示词文件加载；代码中只保留版本号。"""

import re
from functools import lru_cache
from pathlib import Path

from mars.graph.state.errors import MarsError

_PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_VERSION_PATTERN = re.compile(r"^v\d+$")


class PromptNotFoundError(MarsError):
    """提示词版本不存在。"""


def list_versions(node: str) -> list[str]:
    """列出某节点已存在的提示词版本，供前端版本下拉使用。"""
    directory = _PROMPT_ROOT / node
    if not directory.is_dir():
        return []
    versions = [
        path.stem
        for path in directory.iterdir()
        if path.is_file() and _VERSION_PATTERN.match(path.stem)
    ]
    return sorted(versions, key=lambda item: int(item[1:]))


@lru_cache(maxsize=64)
def load_prompt(node: str, version: str) -> str:
    """读取 prompts/<node>/<version>.md；空文件合法。"""
    if not _VERSION_PATTERN.match(version):
        raise PromptNotFoundError(f"非法提示词版本: {version}")
    path = _PROMPT_ROOT / node / f"{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"提示词不存在: {node}/{version}")
    return path.read_text(encoding="utf-8")

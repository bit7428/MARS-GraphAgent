"""提示词文件加载；代码中只保留版本号。"""

import re
from functools import lru_cache
from pathlib import Path

from mars.graph.state.errors import MarsError

_PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_VERSION_PATTERN = re.compile(r"^v\d+$")
_NODE_PATTERN = re.compile(r"^[a-z]+$")


class PromptNotFoundError(MarsError):
    """提示词版本不存在。"""


def _resolve(node: str, version: str) -> Path:
    """把节点与版本解析为受限路径，拒绝任何越界片段。"""
    if not _NODE_PATTERN.match(node):
        raise PromptNotFoundError(f"非法节点名: {node}")
    if not _VERSION_PATTERN.match(version):
        raise PromptNotFoundError(f"非法提示词版本: {version}")
    return _PROMPT_ROOT / node / f"{version}.md"


def prompt_root() -> Path:
    """返回提示词根目录（配置页展示用）。"""
    return _PROMPT_ROOT


def save_prompt(node: str, version: str, content: str) -> None:
    """写入或覆盖某个版本的模板，并失效读取缓存。"""
    path = _resolve(node, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    load_prompt.cache_clear()


def delete_prompt(node: str, version: str) -> None:
    """删除某个版本的模板；调用方负责「不可删除最后一个版本」的校验。"""
    path = _resolve(node, version)
    if not path.is_file():
        raise PromptNotFoundError(f"提示词不存在: {node}/{version}")
    path.unlink()
    load_prompt.cache_clear()


def next_version(node: str) -> str:
    """返回下一个可用版本号。"""
    versions = list_versions(node)
    if not versions:
        return "v1"
    return f"v{max(int(item[1:]) for item in versions) + 1}"


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

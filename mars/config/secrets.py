"""本地 API Key 存储：只写不读回，仅暴露「是否配置 + 尾号」。

设计约束：
- 接口永不返回明文；状态只包含 configured / tail / source。
- 进程环境变量优先于本地文件（显式 export 的值不会被覆盖）。
- 文件权限尽力收紧到 0600；Windows 上 chmod 仅标记所有者。
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SecretSource = Literal["env", "file"]

_FILE_NAME = "secrets.json"
_MIN_LENGTH = 8


@dataclass(frozen=True)
class SecretStatus:
    """单个环境变量对应的密钥状态。"""

    env_name: str
    configured: bool
    tail: str | None
    source: SecretSource | None


class SecretStore:
    """管理进程内环境变量与本地 secrets.json 的密钥写入。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_secret_path()
        self._file_values: dict[str, str] = {}
        self._load()

    @property
    def path(self) -> Path:
        """返回密钥文件路径（供日志/诊断展示，不含内容）。"""
        return self._path

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self._file_values = {
                str(key): str(value) for key, value in raw.items() if isinstance(value, str)
            }
        # 文件值只作兜底，不覆盖显式环境变量
        for name, value in self._file_values.items():
            os.environ.setdefault(name, value)

    def reload(self) -> None:
        """重新读取文件（进程启动与手工编辑场景）。"""
        self._load()

    def status(self, env_name: str) -> SecretStatus:
        """只返回可公开的信息。"""
        configured = bool(os.environ.get(env_name))
        value = os.environ.get(env_name, "")
        source: SecretSource | None = None
        if env_name in self._file_values:
            source = "file"
        elif configured:
            source = "env"
        return SecretStatus(
            env_name=env_name,
            configured=configured,
            tail=f"····{value[-4:]}" if configured and len(value) >= 4 else None,
            source=source,
        )

    def set(self, env_name: str, value: str) -> SecretStatus:
        """写入密钥：同时生效于进程环境与本地文件。"""
        cleaned = value.strip()
        if len(cleaned) < _MIN_LENGTH:
            raise ValueError("密钥长度不足")
        os.environ[env_name] = cleaned
        self._file_values[env_name] = cleaned
        self._persist()
        return self.status(env_name)

    def clear(self, env_name: str) -> SecretStatus:
        """清除密钥：移除文件记录并弹出进程环境变量。"""
        os.environ.pop(env_name, None)
        self._file_values.pop(env_name, None)
        self._persist()
        return self.status(env_name)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._file_values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with suppress(OSError):
            self._path.chmod(0o600)


def default_secret_path() -> Path:
    """默认落在 <MARS_HOME 或工作目录>/.mars/secrets.json。"""
    home = os.environ.get("MARS_HOME")
    base = Path(home) if home else Path.cwd() / ".mars"
    return base / _FILE_NAME

"""运行产物持久化：每次优化一个子文件夹。"""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mars import messages
from mars.graph.state.errors import MarsError, RunNotFoundError
from mars.graph.state.models import IssueDict
from mars.graph.state.schema import GraphState

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STALE_STATUSES = frozenset({"pending", "running", "paused"})
_LOG_REDACTED = frozenset(
    {
        "initial_prompt",
        "working_prompt",
        "optimized_prompt",
        "optimization_goal",
        "report_md",
        "user_supplement",
    }
)


@dataclass(frozen=True)
class ArtifactInfo:
    """前端列表所需的运行产物摘要。"""

    thread_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    finished_at: str
    optimization_goal: str
    tsc_max: int
    m_max: int
    tsc_count: int
    m_count: int
    acceptance: str
    report_available: bool
    log_available: bool
    files: tuple[str, ...]


def normalized_status(status: str, acceptance: str) -> tuple[str, str]:
    """进程重启后，未结束的持久化运行已不可恢复，按中断失败展示。"""
    if status in _STALE_STATUSES:
        return "failed", "进程重启中断"
    return status, acceptance


class RunArtifactStore:
    """以 data/runs/<thread_id>/ 为单位保存报告、日志与状态快照。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def run_dir(self, thread_id: str) -> Path:
        """返回安全的运行子目录，拒绝路径穿越。"""
        path = (self._root / thread_id).resolve()
        if not _RUN_ID.fullmatch(thread_id) or path.parent != self._root.resolve():
            raise MarsError(messages.INVALID_RUN_ID.format(thread_id=thread_id))
        return path

    def create_run(
        self,
        thread_id: str,
        *,
        name: str,
        initial_prompt: str,
        optimization_goal: str,
        performance_criteria: list[dict[str, Any]],
        created_at: str,
        tsc_max: int,
        m_max: int,
    ) -> None:
        """创建子文件夹与初始 meta.json。"""
        path = self.run_dir(thread_id)
        path.mkdir(parents=True, exist_ok=True)
        meta: dict[str, Any] = {
            "thread_id": thread_id,
            "name": name,
            "created_at": created_at,
            "updated_at": created_at,
            "finished_at": "",
            "status": "pending",
            "acceptance": "未验收",
            "optimization_goal": optimization_goal,
            "initial_prompt_sha256": hashlib.sha256(initial_prompt.encode("utf-8")).hexdigest(),
            "initial_prompt_length": len(initial_prompt),
            "performance_criteria": performance_criteria,
            "tsc_max": tsc_max,
            "m_max": m_max,
            "tsc_count": 0,
            "m_count": 0,
        }
        self._write_json(path / "meta.json", meta)
        (path / "run.log").touch(exist_ok=True)
        self.append_event(
            thread_id,
            {"event": "artifacts_created", "thread_id": thread_id, "at": created_at},
        )

    def update_meta(self, thread_id: str, **fields: Any) -> None:
        """合并更新 meta.json，不覆盖未知字段。"""
        path = self.run_dir(thread_id)
        meta_path = path / "meta.json"
        if not meta_path.is_file():
            raise RunNotFoundError(thread_id)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(fields)
        self._write_json(meta_path, meta)

    def append_event(self, thread_id: str, event: dict[str, Any]) -> None:
        """追加结构化日志；日志中不落完整提示词与报告。"""
        path = self.run_dir(thread_id)
        path.mkdir(parents=True, exist_ok=True)
        safe = {key: value for key, value in event.items() if key not in _LOG_REDACTED}
        line = json.dumps(safe, ensure_ascii=False, default=str)
        with (path / "run.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def write_state(self, thread_id: str, state: GraphState) -> None:
        """保存最近一次状态快照。"""
        self._write_json(self.run_dir(thread_id) / "state.json", state)

    def write_error(
        self,
        thread_id: str,
        *,
        issues: list[IssueDict],
        message: str,
    ) -> None:
        """保存失败原因。"""
        self._write_json(
            self.run_dir(thread_id) / "error.json",
            {"thread_id": thread_id, "issues": issues, "message": message},
        )

    def write_report(self, thread_id: str, report_md: str, output_prompt: str) -> None:
        """保存总结报告与最终提示词。"""
        path = self.run_dir(thread_id)
        self._write_text(path / "report.md", report_md)
        self._write_text(path / "output_prompt.txt", output_prompt)

    def list_runs(self) -> list[ArtifactInfo]:
        """扫描子文件夹并返回列表，损坏的 meta 直接跳过。"""
        items: list[ArtifactInfo] = []
        for entry in self._root.iterdir():
            if not entry.is_dir() or not (entry / "meta.json").is_file():
                continue
            try:
                meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
                items.append(
                    ArtifactInfo(
                        thread_id=str(meta.get("thread_id") or entry.name),
                        name=str(meta.get("name") or meta.get("thread_id") or entry.name),
                        status=str(meta.get("status") or "unknown"),
                        created_at=str(meta.get("created_at") or ""),
                        updated_at=str(meta.get("updated_at") or ""),
                        finished_at=str(meta.get("finished_at") or ""),
                        optimization_goal=str(meta.get("optimization_goal") or ""),
                        tsc_max=int(meta.get("tsc_max") or 0),
                        m_max=int(meta.get("m_max") or 0),
                        tsc_count=int(meta.get("tsc_count") or 0),
                        m_count=int(meta.get("m_count") or 0),
                        acceptance=str(meta.get("acceptance") or "未验收"),
                        report_available=(entry / "report.md").is_file(),
                        log_available=(entry / "run.log").is_file(),
                        files=tuple(
                            sorted(item.name for item in entry.iterdir() if item.is_file())
                        ),
                    )
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(items, key=lambda item: (item.created_at, item.thread_id), reverse=True)

    def read_meta(self, thread_id: str) -> dict[str, Any]:
        """读取 meta.json。"""
        path = self.run_dir(thread_id) / "meta.json"
        if not path.is_file():
            raise RunNotFoundError(thread_id)
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    def read_snapshot(self, thread_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """读取持久化的 meta 与 state 快照。"""
        path = self.run_dir(thread_id)
        meta = self.read_meta(thread_id)
        state_path = path / "state.json"
        state: dict[str, Any] = {}
        if state_path.is_file():
            try:
                state = cast(
                    dict[str, Any],
                    json.loads(state_path.read_text(encoding="utf-8")),
                )
            except json.JSONDecodeError:
                state = {}
        return meta, state

    def read_report(self, thread_id: str) -> tuple[str, str]:
        """读取报告与最终提示词；缺失视为运行不存在。"""
        path = self.run_dir(thread_id)
        report_path = path / "report.md"
        if not report_path.is_file():
            raise RunNotFoundError(thread_id)
        prompt_path = path / "output_prompt.txt"
        prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
        return report_path.read_text(encoding="utf-8"), prompt

    def read_log(self, thread_id: str, *, tail: int = 200) -> list[str]:
        """读取结构化日志末尾若干行。"""
        path = self.run_dir(thread_id)
        if not path.is_dir():
            raise RunNotFoundError(thread_id)
        log_path = path / "run.log"
        if not log_path.is_file():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()
        return lines[-max(1, min(tail, 500)) :]

    def delete(self, thread_id: str) -> bool:
        """删除整个运行子文件夹。"""
        path = self.run_dir(thread_id)
        if not path.is_dir():
            return False
        shutil.rmtree(path)
        return True

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        RunArtifactStore._write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)

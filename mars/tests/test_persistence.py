"""运行产物存储测试。"""

import json
from pathlib import Path

import pytest

from mars.graph.state.errors import MarsError, RunNotFoundError
from mars.runtime.persistence import RunArtifactStore, normalized_status
from mars.tests.fixtures.states import base_state


def _store(tmp_path: Path) -> RunArtifactStore:
    store = RunArtifactStore(tmp_path / "runs")
    store.create_run(
        "run-000001",
        name="持久化",
        initial_prompt="初始提示词",
        optimization_goal="目标",
        performance_criteria=[{"name": "正确性", "threshold": 0.9, "comparator": "gte"}],
        created_at="2026-01-01T00:00:00+00:00",
        tsc_max=5,
        m_max=3,
    )
    return store


def test_create_list_report_and_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.update_meta(
        "run-000001",
        status="completed",
        acceptance="通过",
        finished_at="2026-01-01T00:01:00+00:00",
        tsc_count=2,
        m_count=1,
    )
    store.write_state("run-000001", base_state())
    store.write_report("run-000001", "# 报告", "最终提示词")

    info = store.list_runs()[0]
    assert info.name == "持久化"
    assert info.status == "completed"
    assert info.acceptance == "通过"
    assert info.report_available is True
    assert info.log_available is True
    assert {"meta.json", "report.md", "state.json"} <= set(info.files)

    report, prompt = store.read_report("run-000001")
    assert report == "# 报告"
    assert prompt == "最终提示词"
    assert store.read_meta("run-000001")["tsc_count"] == 2

    assert store.delete("run-000001") is True
    assert store.list_runs() == []
    assert store.delete("run-000001") is False


def test_log_redacts_prompts_and_report(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_event(
        "run-000001",
        {
            "event": "run_completed",
            "thread_id": "run-000001",
            "optimized_prompt": "绝密提示词",
            "report_md": "# 绝密报告",
        },
    )
    log = store.read_log("run-000001")
    joined = "\n".join(log)
    assert "绝密提示词" not in joined
    assert "绝密报告" not in joined
    assert "run_completed" in joined


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = RunArtifactStore(tmp_path / "runs")
    with pytest.raises(MarsError):
        store.run_dir("../escape")
    with pytest.raises(MarsError):
        store.run_dir("bad id")


def test_missing_artifacts_raise(tmp_path: Path) -> None:
    store = RunArtifactStore(tmp_path / "runs")
    with pytest.raises(RunNotFoundError):
        store.read_report("run-999999")
    with pytest.raises(RunNotFoundError):
        store.read_snapshot("run-999999")


def test_stale_running_is_reported_as_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    info = store.list_runs()[0]
    assert info.status == "pending"
    status, acceptance = normalized_status(info.status, info.acceptance)
    assert status == "failed"
    assert acceptance == "进程重启中断"


def test_malformed_meta_is_skipped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store.root / "broken").mkdir()
    (store.root / "broken" / "meta.json").write_text("not-json", encoding="utf-8")
    items = store.list_runs()
    assert [item.thread_id for item in items] == ["run-000001"]


def test_meta_contains_no_full_initial_prompt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    meta = json.loads((store.root / "run-000001" / "meta.json").read_text(encoding="utf-8"))
    assert "初始提示词" not in json.dumps(meta, ensure_ascii=False)
    assert meta["initial_prompt_length"] == 5

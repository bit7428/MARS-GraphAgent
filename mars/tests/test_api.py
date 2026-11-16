"""API 集成测试。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from mars.api.app import create_app
from mars.runtime.persistence import RunArtifactStore
from mars.tests.fixtures.fakes import LabeledAdapter, default_handlers

CRITERIA = [{"name": "正确性", "threshold": 0.9, "comparator": "gte"}]
PAYLOAD = {
    "initial_prompt": "初始提示词",
    "optimization_goal": "让提示词更清晰",
    "performance_criteria": CRITERIA,
}


async def _wait(client: AsyncClient, thread_id: str, status: str = "completed") -> dict[str, Any]:
    for _ in range(300):
        response = await client.get(f"/runs/{thread_id}")
        data = cast(dict[str, Any], response.json())
        if data["status"] == status:
            return data
        if data["status"] == "failed":
            raise AssertionError(data)
        await asyncio.sleep(0.01)
    raise AssertionError(f"未在超时内到达状态 {status}")


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
async def client(artifact_root: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(artifact_root),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_health_and_edges(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    edges = (await client.get("/graph/edges")).json()
    assert len(edges) == 12
    assert {edge["edge_id"] for edge in edges} >= {"user->planner", "manager->output"}


async def test_run_happy_path(client: AsyncClient) -> None:
    created = await client.post("/runs", json=PAYLOAD)
    assert created.status_code == 202
    thread_id = created.json()["thread_id"]
    data = await _wait(client, thread_id)
    assert data["status"] == "completed"
    assert data["values"]["optimized_prompt"] == "学生优化后的提示词"
    assert data["values"]["report_md"]


async def test_run_breakpoint_and_resume(client: AsyncClient) -> None:
    payload = {**PAYLOAD, "breakpoints": ["user->planner"]}
    created = await client.post("/runs", json=payload)
    thread_id = created.json()["thread_id"]
    data = await _wait(client, thread_id, status="paused")
    assert data["interrupts"][0]["edge_id"] == "user->planner"
    resumed = await client.post(
        f"/runs/{thread_id}/resume",
        json={"action": "continue", "operator": "tester"},
    )
    assert resumed.status_code == 200
    data = await _wait(client, thread_id)
    assert data["values"]["optimized_prompt"] == "学生优化后的提示词"


async def test_run_breakpoint_update(client: AsyncClient) -> None:
    created = await client.post("/runs", json=PAYLOAD)
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id)
    response = await client.post(
        f"/runs/{thread_id}/breakpoints",
        json={"edge_ids": ["critic->teacher"]},
    )
    assert response.status_code == 200
    assert response.json()["values"]["optimized_prompt"]
    invalid = await client.post(
        f"/runs/{thread_id}/breakpoints",
        json={"edge_ids": ["no->edge"]},
    )
    assert invalid.status_code == 400


async def test_add_breakpoint_while_paused(client: AsyncClient) -> None:
    payload = {**PAYLOAD, "breakpoints": ["user->planner"]}
    created = await client.post("/runs", json=payload)
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id, status="paused")

    updated = await client.post(
        f"/runs/{thread_id}/breakpoints",
        json={"edge_ids": ["planner->teacher"]},
    )
    assert updated.status_code == 200

    await client.post(f"/runs/{thread_id}/resume", json={"action": "continue"})
    data = await _wait(client, thread_id, status="paused")
    assert data["interrupts"][0]["edge_id"] == "planner->teacher"


async def test_invalid_create_request(client: AsyncClient) -> None:
    response = await client.post("/runs", json={"initial_prompt": "x"})
    assert response.status_code == 422


async def test_node_configs(client: AsyncClient) -> None:
    listed = await client.get("/config/nodes")
    assert listed.status_code == 200
    nodes = listed.json()
    assert len(nodes) == 6
    assert all("api_key" not in node for node in nodes)
    assert all(node["available_versions"] == ["v1"] for node in nodes)

    updated = await client.patch(
        "/config/nodes/planner",
        json={"model": "test-model", "temperature": 0.5},
    )
    assert updated.status_code == 200
    assert updated.json()["model"] == "test-model"
    assert updated.json()["temperature"] == 0.5

    missing = await client.patch("/config/nodes/planner", json={"prompt_version": "v99"})
    assert missing.status_code == 400

    reset = await client.delete("/config/nodes/planner")
    assert reset.status_code == 200
    assert reset.json()["model"] != "test-model"

    not_llm = await client.patch("/config/nodes/user", json={"model": "x"})
    assert not_llm.status_code == 400


async def test_run_list_and_meta(client: AsyncClient) -> None:
    meta = (await client.get("/meta")).json()
    assert meta["demo"] is False
    assert meta["tsc_max"] == 5

    created = await client.post("/runs", json={**PAYLOAD, "name": "清单测试"})
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id)

    runs = (await client.get("/runs")).json()
    row = next(item for item in runs if item["thread_id"] == thread_id)
    assert row["status"] == "completed"
    assert row["acceptance"] == "通过"
    assert row["name"] == "清单测试"
    assert row["tsc_max"] == 5
    assert row["m_max"] == 3


async def test_per_run_loop_limits(tmp_path: Path) -> None:
    """运行级上限必须贯穿 Critic 判定与 Output 报告。"""
    app = create_app(
        llm_adapter=LabeledAdapter(default_handlers(critic_passed=False)),
        artifacts=RunArtifactStore(tmp_path / "runs"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post(
            "/runs",
            json={**PAYLOAD, "tsc_max": 1, "m_max": 1},
        )
        data = await _wait(http, created.json()["thread_id"])
        assert data["tsc_max"] == 1
        assert data["m_max"] == 1
        assert data["values"]["tsc_count"] == 1
        assert "TSC 循环：1/1" in data["values"]["report_md"]
        assert "TSC 超限" in data["values"]["report_md"]


async def test_artifacts_are_persisted_and_redacted(
    client: AsyncClient,
    artifact_root: Path,
) -> None:
    created = await client.post("/runs", json={**PAYLOAD, "name": "持久化测试"})
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id)

    run_dir = artifact_root / thread_id
    for name in ("meta.json", "state.json", "report.md", "output_prompt.txt", "run.log"):
        assert (run_dir / name).is_file(), name

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "提示词优化报告" in report
    log = (run_dir / "run.log").read_text(encoding="utf-8")
    assert '"event": "node_end"' in log
    assert "学生优化后的提示词" not in log
    assert "# 提示词优化报告" not in log

    response = await client.get(f"/runs/{thread_id}/report")
    assert response.status_code == 200
    assert response.json()["output_prompt"] == "学生优化后的提示词"

    logs = await client.get(f"/runs/{thread_id}/log", params={"tail": 20})
    assert logs.status_code == 200
    assert logs.json()["lines"]


async def test_history_survives_restart(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    first = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(root),
    )
    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as http:
        created = await http.post("/runs", json={**PAYLOAD, "name": "重启测试"})
        thread_id = created.json()["thread_id"]
        await _wait(http, thread_id)

    second = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(root),
    )
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as http:
        runs = (await http.get("/runs")).json()
        row = next(item for item in runs if item["thread_id"] == thread_id)
        assert row["name"] == "重启测试"
        assert row["status"] == "completed"

        snapshot = (await http.get(f"/runs/{thread_id}")).json()
        assert snapshot["status"] == "completed"
        assert snapshot["values"]["optimized_prompt"] == "学生优化后的提示词"

        report = (await http.get(f"/runs/{thread_id}/report")).json()
        assert "提示词优化报告" in report["report_md"]


async def test_delete_run_data(client: AsyncClient, artifact_root: Path) -> None:
    created = await client.post("/runs", json=PAYLOAD)
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id)
    assert (artifact_root / thread_id).is_dir()

    response = await client.delete(f"/runs/{thread_id}/data")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert not (artifact_root / thread_id).exists()

    runs = (await client.get("/runs")).json()
    assert all(item["thread_id"] != thread_id for item in runs)
    again = await client.delete(f"/runs/{thread_id}/data")
    assert again.status_code == 404


async def test_delete_paused_run_is_rejected(
    client: AsyncClient,
    artifact_root: Path,
) -> None:
    payload = {**PAYLOAD, "breakpoints": ["user->planner"]}
    created = await client.post("/runs", json=payload)
    thread_id = created.json()["thread_id"]
    await _wait(client, thread_id, status="paused")
    response = await client.delete(f"/runs/{thread_id}/data")
    assert response.status_code == 400
    assert (artifact_root / thread_id).is_dir()


async def test_delete_persisted_run_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    first = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(root),
    )
    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as http:
        created = await http.post("/runs", json=PAYLOAD)
        thread_id = created.json()["thread_id"]
        await _wait(http, thread_id)

    second = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(root),
    )
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as http:
        response = await http.delete(f"/runs/{thread_id}/data")
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert not (root / thread_id).exists()
        runs = (await http.get("/runs")).json()
        assert all(item["thread_id"] != thread_id for item in runs)


async def test_new_run_id_does_not_overwrite_existing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunArtifactStore(root)
    first = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=store,
    )
    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as http:
        first_id = (await http.post("/runs", json=PAYLOAD)).json()["thread_id"]
        await _wait(http, first_id)

    second = create_app(
        llm_adapter=LabeledAdapter(default_handlers()),
        artifacts=RunArtifactStore(root),
    )
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as http:
        second_id = (await http.post("/runs", json=PAYLOAD)).json()["thread_id"]
        assert second_id != first_id
        await _wait(http, second_id)

    assert (root / first_id / "report.md").is_file()
    assert (root / second_id / "report.md").is_file()

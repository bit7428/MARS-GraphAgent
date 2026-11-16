"""API 集成测试。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from mars.api.app import create_app
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
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(llm_adapter=LabeledAdapter(default_handlers()))
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


async def test_invalid_create_request(client: AsyncClient) -> None:
    response = await client.post("/runs", json={"initial_prompt": "x"})
    assert response.status_code == 422


async def test_node_configs(client: AsyncClient) -> None:
    listed = await client.get("/config/nodes")
    assert listed.status_code == 200
    nodes = listed.json()
    assert len(nodes) == 6
    assert all("api_key" not in node for node in nodes)

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

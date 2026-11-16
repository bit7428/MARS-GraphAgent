"""FastAPI 入口：DTO 转换、事件流与断点控制。"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mars import messages
from mars.api.schemas import (
    BreakpointUpdateRequest,
    DeleteRunDataView,
    EdgeView,
    LogView,
    NodeConfigUpdate,
    NodeConfigView,
    ReportView,
    ResumeRequest,
    RunCreated,
    RunCreateRequest,
    RunSummary,
    StateView,
)
from mars.config.settings import NodeConfigStore, NodeOverride, load_settings
from mars.graph.builder import build_graph
from mars.graph.edge_table import EDGE_TABLE
from mars.graph.state.constants import LLM_NODES, M_MAX, TSC_MAX
from mars.graph.state.errors import MarsError, RunNotFoundError
from mars.graph.state.models import PerformanceCriterion
from mars.llm.demo import DemoAdapter
from mars.llm.prompts import PromptNotFoundError, load_prompt
from mars.runtime.breakpoints import make_gate
from mars.runtime.checkpoint import build_checkpointer
from mars.runtime.persistence import RunArtifactStore, normalized_status
from mars.runtime.runner import RunManager

router = APIRouter()


class HealthView(BaseModel):
    """健康检查响应。"""

    status: str


class MetaView(BaseModel):
    """运行环境元信息，供前端提示演示模式与默认上限。"""

    demo: bool
    step_delay: float
    tsc_max: int
    m_max: int
    data_dir: str


def _manager(request: Request) -> RunManager:
    return cast(RunManager, request.app.state.manager)


def _store(request: Request) -> NodeConfigStore:
    return cast(NodeConfigStore, request.app.state.node_configs)


def _artifacts(request: Request) -> RunArtifactStore:
    return cast(RunArtifactStore, request.app.state.artifacts)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthView)
async def health() -> HealthView:
    """健康检查。"""
    return HealthView(status="ok")


@router.get("/meta", response_model=MetaView)
async def meta(request: Request) -> MetaView:
    """返回演示模式与默认循环上限。"""
    return MetaView(
        demo=bool(getattr(request.app.state, "demo", False)),
        step_delay=float(getattr(request.app.state, "step_delay", 0.0)),
        tsc_max=TSC_MAX,
        m_max=M_MAX,
        data_dir=str(getattr(request.app.state, "data_dir", "data/runs")),
    )


@router.get("/graph/edges", response_model=list[EdgeView])
async def graph_edges() -> list[EdgeView]:
    """返回边表，供前端配置断点。"""
    return [
        EdgeView(
            edge_id=edge.edge_id,
            source=edge.source,
            target=edge.target,
            kind=edge.kind,
            condition=edge.condition,
            side_effects=list(edge.side_effect),
            breakpoint=edge.breakpoint,
        )
        for edge in EDGE_TABLE
    ]


@router.post("/runs", response_model=RunCreated, status_code=202)
async def create_run(payload: RunCreateRequest, request: Request) -> RunCreated:
    """创建运行并后台启动。"""
    criteria = cast(
        list[PerformanceCriterion],
        [item.model_dump() for item in payload.performance_criteria],
    )
    record = await _manager(request).create_run(
        initial_prompt=payload.initial_prompt,
        optimization_goal=payload.optimization_goal,
        performance_criteria=criteria,
        breakpoints=set(payload.breakpoints),
        node_configs=_store(request).snapshot(),
        name=payload.name or payload.initial_prompt.strip().splitlines()[0][:24],
        tsc_max=payload.tsc_max,
        m_max=payload.m_max,
        step_delay=cast(float, request.app.state.step_delay),
    )
    return RunCreated(thread_id=record.thread_id)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(request: Request) -> list[RunSummary]:
    """返回运行摘要列表，最新在前。"""
    return [RunSummary(**item) for item in await _manager(request).list_runs()]


@router.get("/runs/{thread_id}", response_model=StateView)
async def get_run(thread_id: str, request: Request) -> StateView:
    """返回运行状态；内存缺失时回退到磁盘快照。"""
    manager = _manager(request)
    try:
        record = manager.get(thread_id)
    except RunNotFoundError:
        return _persisted_state(thread_id, _artifacts(request))
    status, values, next_nodes, interrupts = await manager.snapshot(thread_id)
    return StateView(
        thread_id=thread_id,
        name=record.name,
        status=status,
        next=list(next_nodes),
        interrupts=interrupts,
        values=cast(dict[str, Any], values),
        breakpoints=sorted(record.breakpoints),
        tsc_max=record.tsc_max,
        m_max=record.m_max,
        acceptance=record.acceptance,
        created_at=record.created_at,
        finished_at=record.finished_at,
    )


def _persisted_state(thread_id: str, artifacts: RunArtifactStore) -> StateView:
    meta, state = artifacts.read_snapshot(thread_id)
    raw_status = str(meta.get("status") or "completed")
    status, acceptance = normalized_status(
        raw_status,
        str(meta.get("acceptance") or "未验收"),
    )
    finished_at = str(meta.get("finished_at") or "")
    if not finished_at and status != raw_status:
        finished_at = str(meta.get("updated_at") or "")
    return StateView(
        thread_id=thread_id,
        name=str(meta.get("name") or thread_id),
        status=status,
        next=[],
        interrupts=[],
        values=state,
        breakpoints=[],
        tsc_max=int(meta.get("tsc_max") or TSC_MAX),
        m_max=int(meta.get("m_max") or M_MAX),
        acceptance=acceptance,
        created_at=str(meta.get("created_at") or ""),
        finished_at=finished_at,
    )


@router.get("/runs/{thread_id}/report", response_model=ReportView)
async def get_report(thread_id: str, request: Request) -> ReportView:
    """读取磁盘上的总结报告与最终提示词。"""
    report, prompt = _artifacts(request).read_report(thread_id)
    return ReportView(thread_id=thread_id, report_md=report, output_prompt=prompt)


@router.get("/runs/{thread_id}/log", response_model=LogView)
async def get_log(thread_id: str, request: Request, tail: int = 200) -> LogView:
    """读取磁盘上的运行日志末尾。"""
    return LogView(thread_id=thread_id, lines=_artifacts(request).read_log(thread_id, tail=tail))


@router.delete("/runs/{thread_id}/data", response_model=DeleteRunDataView)
async def delete_run_data(thread_id: str, request: Request) -> DeleteRunDataView:
    """删除该优化的整个数据子文件夹。"""
    deleted = await _manager(request).delete_run(thread_id)
    return DeleteRunDataView(thread_id=thread_id, deleted=deleted)


@router.get("/runs/{thread_id}/events")
async def run_events(
    thread_id: str,
    request: Request,
    start_index: int = 0,
) -> StreamingResponse:
    """SSE 事件流：节点开始/结束、断点、完成或失败。"""
    runner = _manager(request)
    runner.get(thread_id)

    async def _stream() -> AsyncIterator[str]:
        async for event in runner.stream_events(thread_id, start_index=start_index):
            yield _sse(event)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{thread_id}/breakpoints", response_model=StateView)
async def set_breakpoints(
    thread_id: str,
    payload: BreakpointUpdateRequest,
    request: Request,
) -> StateView:
    """替换运行中的边断点集合。"""
    await _manager(request).update_breakpoints(thread_id, set(payload.edge_ids))
    return await get_run(thread_id, request)


@router.post("/runs/{thread_id}/resume", response_model=StateView)
async def resume(
    thread_id: str,
    payload: ResumeRequest,
    request: Request,
) -> StateView:
    """恢复断点：继续、改道或中止；可附带用户补充。"""
    await _manager(request).resume(
        thread_id,
        payload.decision(),
        supplement=payload.supplement(),
    )
    return await get_run(thread_id, request)


@router.get("/config/nodes", response_model=list[NodeConfigView])
async def list_node_configs(request: Request) -> list[NodeConfigView]:
    """列出 6 个 LLM 节点的当前配置。"""
    store = _store(request)
    return [NodeConfigView.from_config(node, store.node_config(node)) for node in LLM_NODES]


@router.patch("/config/nodes/{node}", response_model=NodeConfigView)
async def update_node_config(
    node: str,
    payload: NodeConfigUpdate,
    request: Request,
) -> NodeConfigView:
    """修改节点模型配置；密钥仍只从环境变量读取。"""
    _ensure_llm_node(node)
    override = NodeOverride(**payload.model_dump(exclude_unset=True))
    if override.prompt_version is not None:
        try:
            load_prompt(node, override.prompt_version)
        except PromptNotFoundError as exc:
            raise MarsError(str(exc)) from exc
    config = _store(request).update(node, override)
    return NodeConfigView.from_config(node, config)


@router.delete("/config/nodes/{node}", response_model=NodeConfigView)
async def reset_node_config(node: str, request: Request) -> NodeConfigView:
    """恢复节点默认配置。"""
    _ensure_llm_node(node)
    config = _store(request).reset(node)
    return NodeConfigView.from_config(node, config)


def _ensure_llm_node(node: str) -> None:
    if node not in LLM_NODES:
        raise MarsError(messages.NOT_LLM_NODE.format(node=node))


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RunNotFoundError)
    async def _not_found(_: Request, exc: RunNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(MarsError)
    async def _bad_request(_: Request, exc: MarsError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_DEMO_FLAGS = frozenset({"1", "true", "yes", "on"})


def _demo_enabled() -> bool:
    return os.environ.get("MARS_DEMO", "").strip().lower() in _DEMO_FLAGS


def _step_delay(demo: bool) -> float:
    raw = os.environ.get("MARS_DEMO_DELAY", "0.35" if demo else "0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _mount_frontend(app: FastAPI) -> None:
    """托管构建产物；未构建时保持纯 API 形态。"""
    index = _DIST / "index.html"
    if not index.is_file():
        return
    assets = _DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """SPA 回退：静态文件优先，其余交给前端路由。"""
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(
    *,
    manager: RunManager | None = None,
    store: NodeConfigStore | None = None,
    llm_adapter: object | None = None,
    artifacts: RunArtifactStore | None = None,
) -> FastAPI:
    """装配 API；允许测试注入假 LLM 适配器、运行管理器与数据目录。"""
    node_configs = store or NodeConfigStore()
    demo = _demo_enabled() and llm_adapter is None
    adapter = (
        llm_adapter
        if llm_adapter is not None
        else (DemoAdapter(profile=os.environ.get("MARS_DEMO_PROFILE", "default")) if demo else None)
    )
    artifact_store = artifacts or (manager.artifacts if manager is not None else None)
    if artifact_store is None:
        artifact_store = RunArtifactStore(load_settings().data_dir)
    runner = manager
    if runner is None:
        graph = build_graph(gate_factory=make_gate, checkpointer=build_checkpointer())
        runner = RunManager(graph, llm_adapter=adapter, artifacts=artifact_store)

    app = FastAPI(title="MARS-Graph", version="0.1.0")
    app.state.manager = runner
    app.state.node_configs = node_configs
    app.state.artifacts = artifact_store
    app.state.data_dir = str(artifact_store.root)
    app.state.demo = demo
    app.state.step_delay = _step_delay(demo)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _install_error_handlers(app)
    app.include_router(router)
    _mount_frontend(app)
    return app


app = create_app()

"""FastAPI 入口：DTO 转换、事件流与断点控制。"""

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from mars.api.schemas import (
    BreakpointUpdateRequest,
    EdgeView,
    NodeConfigUpdate,
    NodeConfigView,
    ResumeRequest,
    RunCreated,
    RunCreateRequest,
    StateView,
)
from mars.config.settings import NodeConfigStore, NodeOverride
from mars.graph.builder import build_graph
from mars.graph.edge_table import EDGE_TABLE
from mars.graph.state.constants import LLM_NODES
from mars.graph.state.errors import MarsError, RunNotFoundError
from mars.graph.state.models import PerformanceCriterion
from mars.llm.prompts import PromptNotFoundError, load_prompt
from mars.runtime.breakpoints import make_gate
from mars.runtime.checkpoint import build_checkpointer
from mars.runtime.runner import RunManager

router = APIRouter()


class HealthView(BaseModel):
    """健康检查响应。"""

    status: str


def _manager(request: Request) -> RunManager:
    return cast(RunManager, request.app.state.manager)


def _store(request: Request) -> NodeConfigStore:
    return cast(NodeConfigStore, request.app.state.node_configs)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthView)
async def health() -> HealthView:
    """健康检查。"""
    return HealthView(status="ok")


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
    )
    return RunCreated(thread_id=record.thread_id)


@router.get("/runs/{thread_id}", response_model=StateView)
async def get_run(thread_id: str, request: Request) -> StateView:
    """返回运行状态、下一节点与断点载荷。"""
    status, values, next_nodes, interrupts = await _manager(request).snapshot(thread_id)
    return StateView(
        thread_id=thread_id,
        status=status,
        next=list(next_nodes),
        interrupts=interrupts,
        values=cast(dict[str, Any], values),
    )


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
        raise MarsError(f"not an llm node: {node}")


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RunNotFoundError)
    async def _not_found(_: Request, exc: RunNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(MarsError)
    async def _bad_request(_: Request, exc: MarsError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


def create_app(
    *,
    manager: RunManager | None = None,
    store: NodeConfigStore | None = None,
    llm_adapter: object | None = None,
) -> FastAPI:
    """装配 API；允许测试注入假 LLM 适配器与运行管理器。"""
    node_configs = store or NodeConfigStore()
    runner = manager
    if runner is None:
        graph = build_graph(gate_factory=make_gate, checkpointer=build_checkpointer())
        runner = RunManager(graph, llm_adapter=llm_adapter)

    app = FastAPI(title="MARS-Graph", version="0.1.0")
    app.state.manager = runner
    app.state.node_configs = node_configs
    _install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()

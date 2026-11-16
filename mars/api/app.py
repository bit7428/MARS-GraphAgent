"""FastAPI 入口：DTO 转换、事件流与断点控制。"""

import json
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from mars import messages
from mars.api.schemas import (
    BreakpointUpdateRequest,
    ConnectionTestView,
    DeleteRunDataView,
    EdgeView,
    LogView,
    NodeConfigUpdate,
    NodeConfigView,
    PromptView,
    PromptWriteRequest,
    ReportView,
    ResumeRequest,
    RunCreated,
    RunCreateRequest,
    RunSummary,
    SecretSetRequest,
    SecretStatusView,
    StateView,
)
from mars.config.secrets import SecretStore
from mars.config.settings import NodeConfigStore, NodeOverride, load_settings
from mars.graph.builder import build_graph
from mars.graph.edge_table import EDGE_TABLE
from mars.graph.state.constants import LLM_NODES, M_MAX, TSC_MAX
from mars.graph.state.errors import MarsError, RunNotFoundError
from mars.graph.state.models import PerformanceCriterion
from mars.llm.adapter import ChatMessage, OpenAICompatAdapter
from mars.llm.defaults import recommended_template
from mars.llm.prompts import (
    PromptNotFoundError,
    delete_prompt,
    list_versions,
    load_prompt,
    prompt_root,
    save_prompt,
)
from mars.runtime.breakpoints import make_gate
from mars.runtime.checkpoint import build_checkpointer
from mars.runtime.persistence import RunArtifactStore, normalized_status
from mars.runtime.runner import RunManager

router = APIRouter()


class HealthView(BaseModel):
    """健康检查响应。"""

    status: str


class MetaView(BaseModel):
    """运行环境元信息，供前端提示数据目录与默认上限。"""

    tsc_max: int
    m_max: int
    data_dir: str
    secret_path: str
    prompt_root: str


def _manager(request: Request) -> RunManager:
    return cast(RunManager, request.app.state.manager)


def _store(request: Request) -> NodeConfigStore:
    return cast(NodeConfigStore, request.app.state.node_configs)


def _secrets(request: Request) -> SecretStore:
    return cast(SecretStore, request.app.state.secrets)


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
        tsc_max=TSC_MAX,
        m_max=M_MAX,
        data_dir=str(getattr(request.app.state, "data_dir", "data/runs")),
        secret_path=str(_secrets(request).path),
        prompt_root=str(prompt_root()),
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


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _secret_view(
    store: NodeConfigStore,
    secrets: SecretStore,
    env_name: str,
) -> SecretStatusView:
    """组装密钥状态；只包含可公开字段。"""
    status = secrets.status(env_name)
    used_by = [node for node in LLM_NODES if store.node_config(node).api_key_env == env_name]
    return SecretStatusView(
        env_name=env_name,
        configured=status.configured,
        tail=status.tail,
        source=status.source,
        used_by=used_by,
    )


@router.get("/config/secrets", response_model=list[SecretStatusView])
async def list_secrets(request: Request) -> list[SecretStatusView]:
    """列出当前节点引用到的密钥状态，永不返回明文。"""
    store = _store(request)
    secrets = _secrets(request)
    names = sorted({store.node_config(node).api_key_env for node in LLM_NODES})
    return [_secret_view(store, secrets, name) for name in names]


@router.put("/config/secrets/{env_name}", response_model=SecretStatusView)
async def set_secret(
    env_name: str,
    payload: SecretSetRequest,
    request: Request,
) -> SecretStatusView:
    """写入密钥：立即生效并落盘，响应只给尾号。"""
    _ensure_env_name(env_name)
    try:
        _secrets(request).set(env_name, payload.api_key)
    except ValueError as exc:
        raise MarsError(str(exc)) from exc
    return _secret_view(_store(request), _secrets(request), env_name)


@router.delete("/config/secrets/{env_name}", response_model=SecretStatusView)
async def clear_secret(env_name: str, request: Request) -> SecretStatusView:
    """清除密钥：移除本地记录并弹出进程环境变量。"""
    _ensure_env_name(env_name)
    _secrets(request).clear(env_name)
    return _secret_view(_store(request), _secrets(request), env_name)


@router.get("/config/nodes/{node}/prompt", response_model=PromptView)
async def get_prompt(
    node: str,
    request: Request,
    version: str | None = None,
) -> PromptView:
    """读取某个版本的提示词模板。"""
    _ensure_llm_node(node)
    versions = list_versions(node)
    target = version or _store(request).node_config(node).prompt_version
    if target not in versions:
        raise MarsError(f"提示词版本不存在: {node}/{target}")
    return PromptView(
        node=node,
        version=target,
        content=load_prompt(node, target),
        versions=versions,
        recommended=recommended_template(node),
    )


@router.put("/config/nodes/{node}/prompt", response_model=PromptView)
async def put_prompt(
    node: str,
    payload: PromptWriteRequest,
    request: Request,
) -> PromptView:
    """写入或覆盖模板；写入后立即失效读取缓存。"""
    _ensure_llm_node(node)
    try:
        save_prompt(node, payload.version, payload.content)
    except PromptNotFoundError as exc:
        raise MarsError(str(exc)) from exc
    return await get_prompt(node, request, payload.version)


@router.delete("/config/nodes/{node}/prompt", response_model=PromptView)
async def remove_prompt(node: str, request: Request, version: str) -> PromptView:
    """删除模板版本；至少保留一个且不可删除在用版本。"""
    _ensure_llm_node(node)
    versions = list_versions(node)
    if version not in versions:
        raise MarsError(f"提示词版本不存在: {node}/{version}")
    if len(versions) <= 1:
        raise MarsError("至少保留一个提示词版本")
    if _store(request).node_config(node).prompt_version == version:
        raise MarsError("该版本正在被当前节点使用，请先切换版本再删除")
    try:
        delete_prompt(node, version)
    except PromptNotFoundError as exc:
        raise MarsError(str(exc)) from exc
    remaining = list_versions(node)
    return await get_prompt(node, request, remaining[-1])


@router.post("/config/nodes/{node}/test", response_model=ConnectionTestView)
async def test_node(node: str, request: Request) -> ConnectionTestView:
    """用最短提示词验证模型与密钥是否可用。"""
    _ensure_llm_node(node)
    config = _store(request).node_config(node)
    adapter = getattr(request.app.state, "llm_adapter", None) or OpenAICompatAdapter()
    payload: list[ChatMessage] = [{"role": "user", "content": "ping"}]
    started = time.perf_counter()
    try:
        completion = await run_in_threadpool(adapter.complete, payload, config)
    except Exception as exc:  # 供应商异常统一转成可读结果
        return ConnectionTestView(
            ok=False,
            model=config.model,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            message=f"{type(exc).__name__}: {exc}"[:240],
        )
    return ConnectionTestView(
        ok=True,
        model=completion.model,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        message=str(completion.text)[:120],
    )


def _ensure_env_name(env_name: str) -> None:
    if not _ENV_NAME.match(env_name):
        raise MarsError(f"非法环境变量名: {env_name}")


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
    secrets: SecretStore | None = None,
) -> FastAPI:
    """装配 API；允许测试注入假 LLM 适配器、运行管理器与数据目录。"""
    node_configs = store or NodeConfigStore()
    secret_store = secrets or SecretStore()
    artifact_store = artifacts or (manager.artifacts if manager is not None else None)
    if artifact_store is None:
        artifact_store = RunArtifactStore(load_settings().data_dir)
    runner = manager
    if runner is None:
        graph = build_graph(gate_factory=make_gate, checkpointer=build_checkpointer())
        runner = RunManager(graph, llm_adapter=llm_adapter, artifacts=artifact_store)

    app = FastAPI(title="MARS-Graph", version="0.1.0")
    app.state.manager = runner
    app.state.node_configs = node_configs
    app.state.artifacts = artifact_store
    app.state.secrets = secret_store
    app.state.llm_adapter = llm_adapter
    app.state.data_dir = str(artifact_store.root)
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

"""图执行入口：事件流、断点暂停/恢复、异常收敛。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from mars import messages
from mars.config.settings import NodeLLMConfig
from mars.graph.edge_table import find_edge
from mars.graph.state.constants import BUSINESS_FIELDS, M_MAX, NODE_NAMES, TSC_MAX
from mars.graph.state.errors import FatalStateError, MarsError, RunNotFoundError
from mars.graph.state.models import IssueDict, PerformanceCriterion
from mars.graph.state.schema import GraphState
from mars.runtime.breakpoints import build_resume_command, make_gate
from mars.runtime.persistence import ArtifactInfo, RunArtifactStore, normalized_status
from mars.runtime.reporting import acceptance_of, render_report
from mars.utils.clock import Clock, IdGenerator, SequentialIdGenerator, SystemClock

logger = logging.getLogger("mars.runtime")

TERMINAL_STATUSES = frozenset({"completed", "failed"})
Graph = CompiledStateGraph[GraphState, Any, GraphState, GraphState]


@dataclass
class RunRecord:
    """单次运行的进程内状态。"""

    thread_id: str
    node_configs: dict[str, NodeLLMConfig]
    name: str = ""
    breakpoints: set[str] = field(default_factory=set)
    status: str = "pending"
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    pending_supplement: dict[str, str] | None = None
    tsc_max: int = TSC_MAX
    m_max: int = M_MAX
    step_delay: float = 0.0
    created_at: str = ""
    finished_at: str = ""
    acceptance: str = "未验收"


class RunManager:
    """管理运行生命周期；检查点保存在图内，进程重启即丢失。"""

    def __init__(
        self,
        graph: Graph,
        *,
        clock: Clock | None = None,
        idgen: IdGenerator | None = None,
        llm_adapter: object | None = None,
        artifacts: RunArtifactStore | None = None,
    ) -> None:
        self._graph = graph
        self._clock = clock or SystemClock()
        self._idgen = idgen or SequentialIdGenerator()
        self._llm_adapter = llm_adapter
        self._artifacts = artifacts
        self._runs: dict[str, RunRecord] = {}

    async def create_run(
        self,
        *,
        initial_prompt: str,
        optimization_goal: str,
        performance_criteria: list[PerformanceCriterion],
        breakpoints: set[str] | None = None,
        node_configs: dict[str, NodeLLMConfig] | None = None,
        name: str = "",
        tsc_max: int = TSC_MAX,
        m_max: int = M_MAX,
        step_delay: float = 0.0,
    ) -> RunRecord:
        """创建并后台启动运行。"""
        self._validate_breakpoints(breakpoints or set())
        thread_id = self._idgen.new_id("run")
        if self._artifacts is not None:
            while self._artifacts.run_dir(thread_id).exists():
                thread_id = self._idgen.new_id("run")
        begin = getattr(self._llm_adapter, "begin_run", None)
        if callable(begin):
            begin()
        created_at = self._clock.now().isoformat()
        resolved_name = name.strip() or thread_id
        if self._artifacts is not None:
            self._artifacts.create_run(
                thread_id,
                name=resolved_name,
                initial_prompt=initial_prompt,
                optimization_goal=optimization_goal,
                performance_criteria=cast(list[dict[str, Any]], performance_criteria),
                created_at=created_at,
                tsc_max=tsc_max,
                m_max=m_max,
            )
        record = RunRecord(
            thread_id=thread_id,
            node_configs=node_configs or {},
            breakpoints=set(breakpoints or set()),
            name=resolved_name,
            tsc_max=tsc_max,
            m_max=m_max,
            step_delay=max(0.0, step_delay),
            created_at=created_at,
        )
        self._runs[thread_id] = record
        initial: GraphState = {
            "initial_prompt": initial_prompt,
            "optimization_goal": optimization_goal,
            "performance_criteria": performance_criteria,
            "tsc_count": 0,
            "m_count": 0,
        }
        await self._emit(record, {"event": "run_started", "thread_id": thread_id})
        record.status = "running"
        self._update_meta(record, state=initial)
        record.task = asyncio.create_task(self._drive(record, initial))
        return record

    def get(self, thread_id: str) -> RunRecord:
        """按 thread_id 取运行记录。"""
        record = self._runs.get(thread_id)
        if record is None:
            raise RunNotFoundError(thread_id)
        return record

    @property
    def artifacts(self) -> RunArtifactStore | None:
        """当前运行管理器的产物存储。"""
        return self._artifacts

    async def resume(
        self,
        thread_id: str,
        decision: object,
        *,
        supplement: dict[str, str] | None = None,
    ) -> RunRecord:
        """按 continue / reroute:<node> / abort 恢复。"""
        record = self.get(thread_id)
        if record.status != "paused":
            raise MarsError(messages.RUN_NOT_RESUMABLE.format(status=record.status))
        record.status = "running"
        record.pending_supplement = supplement
        await self._emit(
            record,
            {"event": "run_resumed", "thread_id": thread_id, "decision": decision},
        )
        command = build_resume_command(decision)
        record.task = asyncio.create_task(self._drive(record, command))
        return record

    async def update_breakpoints(self, thread_id: str, edge_ids: set[str]) -> RunRecord:
        """运行中可动态设置/取消边断点。"""
        self._validate_breakpoints(edge_ids)
        record = self.get(thread_id)
        # 原地更新，使当前运行已捕获的集合引用立即生效
        record.breakpoints.clear()
        record.breakpoints.update(edge_ids)
        await self._emit(
            record,
            {"event": "breakpoints_updated", "thread_id": thread_id, "edge_ids": sorted(edge_ids)},
        )
        return record

    async def snapshot(
        self, thread_id: str
    ) -> tuple[str, GraphState, tuple[str, ...], list[object]]:
        """返回状态快照、下一个待执行节点与待处理断点载荷。"""
        record = self.get(thread_id)
        config = cast(RunnableConfig, {"configurable": {"thread_id": thread_id}})
        state = await self._graph.aget_state(config)
        interrupts = [interrupt.value for task in state.tasks for interrupt in task.interrupts]
        return record.status, cast(GraphState, state.values), tuple(state.next), interrupts

    async def list_runs(self) -> list[dict[str, Any]]:
        """合并内存运行与磁盘产物，最新在前；重启后仍保留历史。"""
        items: list[dict[str, Any]] = []
        live_ids: set[str] = set()
        for record in self._runs.values():
            live_ids.add(record.thread_id)
            _, values, next_nodes, _ = await self.snapshot(record.thread_id)
            items.append(
                {
                    "thread_id": record.thread_id,
                    "name": record.name or record.thread_id,
                    "status": record.status,
                    "created_at": record.created_at,
                    "finished_at": record.finished_at,
                    "tsc_max": record.tsc_max,
                    "m_max": record.m_max,
                    "tsc_count": int(values.get("tsc_count") or 0),
                    "m_count": int(values.get("m_count") or 0),
                    "acceptance": record.acceptance,
                    "next": list(next_nodes),
                }
            )
        if self._artifacts is not None:
            for info in self._artifacts.list_runs():
                if info.thread_id in live_ids:
                    continue
                items.append(self._artifact_summary(info))
        return sorted(items, key=lambda item: (item["created_at"], item["thread_id"]), reverse=True)

    @staticmethod
    def _artifact_summary(info: ArtifactInfo) -> dict[str, Any]:
        status, acceptance = normalized_status(info.status, info.acceptance)
        finished_at = info.finished_at or (info.updated_at if status != info.status else "")
        return {
            "thread_id": info.thread_id,
            "name": info.name,
            "status": status,
            "created_at": info.created_at,
            "finished_at": finished_at,
            "tsc_max": info.tsc_max or TSC_MAX,
            "m_max": info.m_max or M_MAX,
            "tsc_count": info.tsc_count,
            "m_count": info.m_count,
            "acceptance": acceptance,
            "next": [],
        }

    async def delete_run(self, thread_id: str) -> bool:
        """删除运行子文件夹；运行未结束时拒绝。"""
        record = self._runs.get(thread_id)
        if record is None:
            # 无内存记录即没有活动任务，允许清理重启后遗留的数据
            deleted = self._artifacts.delete(thread_id) if self._artifacts is not None else False
            if not deleted:
                raise RunNotFoundError(thread_id)
            return True
        if record.status in {"pending", "running", "paused"}:
            raise MarsError(messages.RUN_BUSY.format(thread_id=thread_id))
        deleted = self._artifacts.delete(thread_id) if self._artifacts is not None else False
        self._runs.pop(thread_id, None)
        return deleted or record is not None

    async def stream_events(
        self,
        thread_id: str,
        *,
        start_index: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 数据源：先回放缓冲，再等待新事件。"""
        record = self.get(thread_id)
        index = max(0, start_index)
        while True:
            async with record.changed:
                while index >= len(record.events) and record.status not in TERMINAL_STATUSES:
                    await record.changed.wait()
                batch = record.events[index:]
                index = len(record.events)
            for event in batch:
                yield event
            if record.status in TERMINAL_STATUSES and index >= len(record.events):
                return

    async def _drive(self, record: RunRecord, payload: Any) -> None:
        config = self._config(record)
        try:
            async for event in self._graph_events(record, payload, config):
                await self._emit(record, event)
            await self._finish(record, config)
        except FatalStateError as exc:
            await self._fail(
                record,
                [issue.to_dict() for issue in exc.issues],
                str(exc),
                config,
            )
        except MarsError as exc:
            await self._fail(record, [], str(exc), config)
        except Exception as exc:
            logger.exception("run_error")
            await self._fail(record, [], f"{type(exc).__name__}: {exc}", config)
        finally:
            record.pending_supplement = None
            async with record.changed:
                record.changed.notify_all()

    def _config(self, record: RunRecord) -> RunnableConfig:
        configurable: dict[str, Any] = {
            "thread_id": record.thread_id,
            "breakpoints": record.breakpoints,
            "node_configs": record.node_configs,
            "report_renderer": partial(
                render_report,
                tsc_max=record.tsc_max,
                m_max=record.m_max,
            ),
            "tsc_max": record.tsc_max,
            "m_max": record.m_max,
            "clock": self._clock,
            "id_generator": self._idgen,
        }
        if record.pending_supplement is not None:
            configurable["user_supplement"] = record.pending_supplement
        if self._llm_adapter is not None:
            configurable["llm_adapter"] = self._llm_adapter
        return cast(
            RunnableConfig,
            {"configurable": configurable, "recursion_limit": 200},
        )

    async def _finish(self, record: RunRecord, config: RunnableConfig) -> None:
        state = await self._graph.aget_state(config)
        interrupts = [interrupt.value for task in state.tasks for interrupt in task.interrupts]
        if interrupts:
            record.status = "paused"
            await self._persist_finish(record, cast(GraphState, state.values))
            payload = interrupts[0]
            counters = (
                cast(dict[str, Any], payload).get("counters", {})
                if isinstance(payload, dict)
                else {}
            )
            await self._emit(
                record,
                {
                    "event": "breakpoint",
                    "thread_id": record.thread_id,
                    "payload": payload,
                    "counters": counters,
                },
            )
            return
        record.status = "completed"
        final = cast(GraphState, state.values)
        record.acceptance = acceptance_of(final, m_max=record.m_max)
        record.finished_at = self._clock.now().isoformat()
        await self._persist_finish(record, final)
        await self._emit(
            record,
            {
                "event": "run_completed",
                "thread_id": record.thread_id,
                "optimized_prompt": final.get("optimized_prompt") or "",
                "report_md": final.get("report_md") or "",
            },
        )

    async def _persist_finish(self, record: RunRecord, state: GraphState) -> None:
        if self._artifacts is None:
            return
        try:
            self._artifacts.write_state(record.thread_id, state)
            if record.status == "completed":
                self._artifacts.write_report(
                    record.thread_id,
                    state.get("report_md") or "",
                    state.get("optimized_prompt") or "",
                )
            self._update_meta(record, state)
        except (OSError, MarsError) as exc:
            logger.exception("artifact_write_failed")
            await self._emit(
                record,
                {
                    "event": "artifact_error",
                    "thread_id": record.thread_id,
                    "message": type(exc).__name__,
                },
            )

    def _update_meta(self, record: RunRecord, state: GraphState | None = None) -> None:
        if self._artifacts is None:
            return
        fields: dict[str, Any] = {
            "name": record.name or record.thread_id,
            "status": record.status,
            "updated_at": self._clock.now().isoformat(),
            "finished_at": record.finished_at,
            "acceptance": record.acceptance,
            "tsc_max": record.tsc_max,
            "m_max": record.m_max,
        }
        if state is not None:
            fields["tsc_count"] = int(state.get("tsc_count") or 0)
            fields["m_count"] = int(state.get("m_count") or 0)
        self._artifacts.update_meta(record.thread_id, **fields)

    async def _fail(
        self,
        record: RunRecord,
        issues: list[IssueDict],
        message: str,
        config: RunnableConfig | None = None,
    ) -> None:
        record.status = "failed"
        record.finished_at = self._clock.now().isoformat()
        record.acceptance = (
            "已终止（1 级报错）" if any(issue.get("level") == 1 for issue in issues) else "异常终止"
        )
        if self._artifacts is not None:
            try:
                if config is not None:
                    state = await self._graph.aget_state(config)
                    self._artifacts.write_state(record.thread_id, cast(GraphState, state.values))
                self._artifacts.write_error(record.thread_id, issues=issues, message=message)
                self._update_meta(record)
            except (OSError, MarsError):
                logger.exception("artifact_write_failed")
        await self._emit(
            record,
            {
                "event": "run_failed",
                "thread_id": record.thread_id,
                "issues": issues,
                "message": message,
            },
        )

    async def _graph_events(
        self,
        record: RunRecord,
        payload: Any,
        config: RunnableConfig,
    ) -> AsyncIterator[dict[str, Any]]:
        async for raw in self._graph.astream_events(payload, config, version="v2"):
            event = cast(dict[str, Any], raw)
            kind = event.get("event")
            name = event.get("name")
            metadata = cast(Mapping[str, Any], event.get("metadata") or {})
            node = metadata.get("langgraph_node") or name
            if name not in NODE_NAMES or node not in NODE_NAMES:
                continue
            if kind == "on_chain_start":
                await self._pace(record)
                yield {"event": "node_start", "thread_id": record.thread_id, "node": node}
            elif kind == "on_chain_end":
                data = cast(Mapping[str, Any], event.get("data") or {})
                output = data.get("output")
                partial = output if isinstance(output, dict) else {}
                writes = [key for key in partial if key != "trace" and key in _WRITABLE_VIEW]
                trace = partial.get("trace")
                await self._pace(record)
                yield {
                    "event": "node_end",
                    "thread_id": record.thread_id,
                    "node": node,
                    "writes": writes,
                    "trace": trace[0] if isinstance(trace, list) and trace else None,
                }
            elif kind == "on_chain_error":
                await self._pace(record)
                yield {
                    "event": "node_error",
                    "thread_id": record.thread_id,
                    "node": node,
                    "message": str(event.get("data")),
                }

    async def _pace(self, record: RunRecord) -> None:
        """演示模式下放慢事件节奏，便于观察状态图动画。"""
        if record.step_delay > 0:
            await asyncio.sleep(record.step_delay)

    async def _emit(self, record: RunRecord, event: dict[str, Any]) -> None:
        async with record.changed:
            record.events.append(event)
            record.changed.notify_all()
        if self._artifacts is not None:
            try:
                self._artifacts.append_event(record.thread_id, event)
            except (OSError, MarsError):
                logger.exception("artifact_write_failed")
        logger.info(
            json.dumps(
                {
                    "level": "info",
                    "code": event.get("event"),
                    "run_id": record.thread_id,
                    "thread_id": record.thread_id,
                    "node": event.get("node"),
                    "edge_id": cast(dict[str, Any], event.get("payload") or {}).get("edge_id")
                    if isinstance(event.get("payload"), dict)
                    else None,
                },
                ensure_ascii=False,
            )
        )

    def _validate_breakpoints(self, edge_ids: set[str]) -> None:
        unknown = sorted(edge_id for edge_id in edge_ids if find_edge(edge_id) is None)
        if unknown:
            raise MarsError(messages.UNKNOWN_EDGE.format(ids=",".join(unknown)))


_WRITABLE_VIEW = frozenset(
    {
        *BUSINESS_FIELDS,
        "route_critic",
        "route_target",
        "route_manager",
        "report_md",
    }
)


def build_run_manager(graph: Graph, *, clock: Clock | None = None) -> RunManager:
    """便捷入口；gate 工厂固定为 runtime 实现。"""
    return RunManager(graph, clock=clock)


__all__ = ["RunManager", "RunRecord", "build_run_manager", "make_gate"]

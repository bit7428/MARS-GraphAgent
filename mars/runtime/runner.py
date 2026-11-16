"""图执行入口：事件流、断点暂停/恢复、异常收敛。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from mars import messages
from mars.config.settings import NodeLLMConfig
from mars.graph.edge_table import find_edge
from mars.graph.state.constants import BUSINESS_FIELDS, NODE_NAMES
from mars.graph.state.errors import FatalStateError, MarsError, RunNotFoundError
from mars.graph.state.models import IssueDict, PerformanceCriterion
from mars.graph.state.schema import GraphState
from mars.runtime.breakpoints import build_resume_command, make_gate
from mars.runtime.reporting import render_report
from mars.utils.clock import Clock, IdGenerator, SequentialIdGenerator, SystemClock

logger = logging.getLogger("mars.runtime")

TERMINAL_STATUSES = frozenset({"completed", "failed"})
Graph = CompiledStateGraph[GraphState, Any, GraphState, GraphState]


@dataclass
class RunRecord:
    """单次运行的进程内状态。"""

    thread_id: str
    node_configs: dict[str, NodeLLMConfig]
    breakpoints: set[str] = field(default_factory=set)
    status: str = "pending"
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    pending_supplement: dict[str, str] | None = None


class RunManager:
    """管理运行生命周期；检查点保存在图内，进程重启即丢失。"""

    def __init__(
        self,
        graph: Graph,
        *,
        clock: Clock | None = None,
        idgen: IdGenerator | None = None,
        llm_adapter: object | None = None,
    ) -> None:
        self._graph = graph
        self._clock = clock or SystemClock()
        self._idgen = idgen or SequentialIdGenerator()
        self._llm_adapter = llm_adapter
        self._runs: dict[str, RunRecord] = {}

    async def create_run(
        self,
        *,
        initial_prompt: str,
        optimization_goal: str,
        performance_criteria: list[PerformanceCriterion],
        breakpoints: set[str] | None = None,
        node_configs: dict[str, NodeLLMConfig] | None = None,
    ) -> RunRecord:
        """创建并后台启动运行。"""
        self._validate_breakpoints(breakpoints or set())
        thread_id = self._idgen.new_id("run")
        record = RunRecord(
            thread_id=thread_id,
            node_configs=node_configs or {},
            breakpoints=set(breakpoints or set()),
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
        record.task = asyncio.create_task(self._drive(record, initial))
        return record

    def get(self, thread_id: str) -> RunRecord:
        """按 thread_id 取运行记录。"""
        record = self._runs.get(thread_id)
        if record is None:
            raise RunNotFoundError(thread_id)
        return record

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
            )
        except MarsError as exc:
            await self._fail(record, [], str(exc))
        except Exception as exc:
            logger.exception("run_error")
            await self._fail(record, [], f"{type(exc).__name__}: {exc}")
        finally:
            record.pending_supplement = None
            async with record.changed:
                record.changed.notify_all()

    def _config(self, record: RunRecord) -> RunnableConfig:
        configurable: dict[str, Any] = {
            "thread_id": record.thread_id,
            "breakpoints": record.breakpoints,
            "node_configs": record.node_configs,
            "report_renderer": render_report,
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
        await self._emit(
            record,
            {
                "event": "run_completed",
                "thread_id": record.thread_id,
                "optimized_prompt": final.get("optimized_prompt") or "",
                "report_md": final.get("report_md") or "",
            },
        )

    async def _fail(
        self,
        record: RunRecord,
        issues: list[IssueDict],
        message: str,
    ) -> None:
        record.status = "failed"
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
                yield {"event": "node_start", "thread_id": record.thread_id, "node": node}
            elif kind == "on_chain_end":
                data = cast(Mapping[str, Any], event.get("data") or {})
                output = data.get("output")
                partial = output if isinstance(output, dict) else {}
                writes = [key for key in partial if key != "trace" and key in _WRITABLE_VIEW]
                trace = partial.get("trace")
                yield {
                    "event": "node_end",
                    "thread_id": record.thread_id,
                    "node": node,
                    "writes": writes,
                    "trace": trace[0] if isinstance(trace, list) and trace else None,
                }
            elif kind == "on_chain_error":
                yield {
                    "event": "node_error",
                    "thread_id": record.thread_id,
                    "node": node,
                    "message": str(event.get("data")),
                }

    async def _emit(self, record: RunRecord, event: dict[str, Any]) -> None:
        async with record.changed:
            record.events.append(event)
            record.changed.notify_all()
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

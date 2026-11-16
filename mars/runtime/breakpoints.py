"""边级断点：挂起、恢复与人工改道（Command 唯一允许出现的位置）。"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command, interrupt

from mars import messages
from mars.graph.contract import CONTRACTS, configurable
from mars.graph.edge_table import EdgeSpec, edges_from
from mars.graph.state.constants import BUSINESS_FIELDS, REROUTE_GLOBAL_TARGETS
from mars.graph.state.errors import (
    E2_BREAKPOINT_PAYLOAD,
    E2_REROUTE_REJECTED,
    StateIssue,
)
from mars.graph.state.models import NodeTrace
from mars.graph.state.schema import GraphState
from mars.graph.state.validate import validate_state
from mars.utils.clock import Clock, SystemClock

GateFn = Callable[[GraphState, RunnableConfig], Command[Any]]


@dataclass(frozen=True)
class BreakpointDecision:
    """恢复指令解析结果。"""

    action: Literal["continue", "reroute", "abort", "invalid"]
    target: str | None = None
    operator: str | None = None
    error: str | None = None


def state_digest(state: GraphState) -> str:
    """只对业务字段求哈希，避免把完整状态推给前端。"""
    raw = cast(Mapping[str, Any], state)
    payload = {field: raw[field] for field in BUSINESS_FIELDS if field in raw}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clock(config: RunnableConfig) -> Clock:
    injected = configurable(config).get("clock")
    return cast(Clock, injected) if injected is not None else SystemClock()


def _hit_breakpoint(config: RunnableConfig, edge_id: str) -> bool:
    configured = configurable(config).get("breakpoints")
    if isinstance(configured, set | list | tuple | frozenset):
        return edge_id in configured
    return False


def _route_value(state: GraphState, edge: EdgeSpec) -> str:
    key = {
        "critic": "route_critic",
        "target": "route_target",
        "manager": "route_manager",
    }.get(edge.source)
    if key is None:
        return edge.target
    return cast(str, state.get(key) or edge.target)


def _allowed_reroutes(state: GraphState, edge: EdgeSpec) -> list[str]:
    """R7.7：当前源候选目标 ∪ 全局候选；output 仅在 3 非空时可选。"""
    candidates = {item.target for item in edges_from(edge.source)} | set(REROUTE_GLOBAL_TARGETS)
    if not (state.get("optimized_prompt") or "").strip():
        candidates.discard("output")
    else:
        candidates.add("output")
    return sorted(candidates)


def _parse_decision(decision: object) -> BreakpointDecision:
    if decision == "continue":
        return BreakpointDecision(action="continue")
    if decision == "abort":
        return BreakpointDecision(action="abort")
    if isinstance(decision, str) and decision.startswith("reroute:"):
        return BreakpointDecision(action="reroute", target=decision.split(":", 1)[1])
    if isinstance(decision, Mapping):
        record = cast(Mapping[str, object], decision)
        action = record.get("action")
        operator = record.get("operator")
        return BreakpointDecision(
            action=cast(Any, action) if action in {"continue", "reroute", "abort"} else "invalid",
            target=cast(str, record.get("target"))
            if isinstance(record.get("target"), str)
            else None,
            operator=operator if isinstance(operator, str) else None,
            error=None
            if action in {"continue", "reroute", "abort"}
            else messages.BREAKPOINT_UNKNOWN_ACTION,
        )
    return BreakpointDecision(action="invalid", error=messages.BREAKPOINT_BAD_PAYLOAD)


def _reroute_rejection(state: GraphState, edge: EdgeSpec, target: str) -> StateIssue | None:
    """只读契约校验；失败则拒绝改道。"""
    if target not in _allowed_reroutes(state, edge):
        return StateIssue(
            code=E2_REROUTE_REJECTED,
            level=2,
            field="route",
            message=messages.REROUTE_NOT_ALLOWED.format(target=target),
        )
    contract = CONTRACTS[target]
    issues = validate_state(state, required=contract.required, optional=contract.optional)
    blocking = [
        issue
        for issue in issues
        if issue.level == 1 or (issue.field is not None and issue.field in contract.required)
    ]
    if blocking:
        codes = ",".join(issue.code for issue in blocking)
        return StateIssue(
            code=E2_REROUTE_REJECTED,
            level=2,
            field="route",
            message=messages.REROUTE_CONTRACT_FAILED.format(target=target, codes=codes),
        )
    return None


def _trace(
    config: RunnableConfig,
    *,
    edge: EdgeSpec,
    original: str,
    new_route: str | None,
    operator: str | None,
    summary: str,
    issues: list[StateIssue],
) -> NodeTrace:
    clock = _clock(config)
    return {
        "node": f"gate:{edge.edge_id}",
        "started_at": clock.now().isoformat(),
        "duration_ms": 0.0,
        "model": None,
        "prompt_version": None,
        "issues": [issue.to_dict() for issue in issues],
        "writes": [],
        "side_effects": [f"breakpoint:{edge.edge_id}"],
        "summary": summary,
        "human_intervention": True,
        "original_route": original,
        "new_route": new_route,
        "operator": operator,
        "at": clock.now().isoformat(),
    }


def _handle_resume(
    state: GraphState,
    config: RunnableConfig,
    edge: EdgeSpec,
    decision: object,
) -> Command[Any]:
    parsed = _parse_decision(decision)
    issues: list[StateIssue] = []
    original = _route_value(state, edge)
    target = original
    summary = messages.GATE_CONTINUE
    new_route: str | None = original

    if parsed.action == "invalid":
        issues.append(
            StateIssue(
                code=E2_BREAKPOINT_PAYLOAD,
                level=2,
                field="decision",
                message=parsed.error or messages.BREAKPOINT_BAD_PAYLOAD,
            )
        )
        summary = messages.GATE_INVALID
    elif parsed.action == "abort":
        target = END
        new_route = None
        summary = messages.GATE_ABORT
    elif parsed.action == "reroute":
        requested = parsed.target or ""
        rejection = _reroute_rejection(state, edge, requested)
        if rejection is not None:
            issues.append(rejection)
            summary = messages.GATE_REROUTE_REJECTED.format(target=requested)
        else:
            target = requested
            new_route = requested
            summary = messages.GATE_REROUTE.format(original=original, target=requested)

    trace = _trace(
        config,
        edge=edge,
        original=original,
        new_route=new_route,
        operator=parsed.operator,
        summary=summary,
        issues=issues,
    )
    return Command(goto=target, update={"trace": [trace]})


def make_gate(edge: EdgeSpec) -> GateFn:
    """构造一条边的 gate：源节点更新后、目标节点执行前挂起。"""

    def gate(state: GraphState, config: RunnableConfig) -> Command[Any]:
        """命中断点时挂起，否则直接转交目标节点。"""
        route = _route_value(state, edge)
        if not _hit_breakpoint(config, edge.edge_id):
            return Command(goto=route)

        payload: dict[str, Any] = {
            "edge_id": edge.edge_id,
            "state_digest": state_digest(state),
            "route": route,
            "allowed_reroutes": _allowed_reroutes(state, edge),
            "counters": {
                "tsc_count": state.get("tsc_count", 0),
                "m_count": state.get("m_count", 0),
            },
        }
        decision = interrupt(payload)
        return _handle_resume(state, config, edge, decision)

    return gate


def build_resume_command(decision: object) -> Command[Any]:
    """API/runtime 恢复入口；Command 只在模块内构造。"""
    return Command(resume=decision)

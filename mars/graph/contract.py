"""节点契约：声明读写清单、统一校验、追踪与越界检查。"""

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from mars.config.settings import NodeLLMConfig, default_node_config
from mars.graph.state.constants import BUSINESS_FIELDS, M_MAX, NODE_NAMES, TSC_MAX
from mars.graph.state.errors import (
    CodingContractError,
    FatalStateError,
    StateIssue,
)
from mars.graph.state.models import NodeTrace
from mars.graph.state.schema import GraphState
from mars.graph.state.validate import fatal_issues, validate_state
from mars.utils.clock import Clock, IdGenerator, SequentialIdGenerator, SystemClock

NodeFn = Callable[[GraphState, RunnableConfig], dict[str, Any]]


@dataclass(frozen=True)
class NodeContract:
    """单个节点的必填、待选、业务写入与副作用写入声明。"""

    node: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    side_effect_writes: tuple[str, ...] = ()
    route_key: str | None = None


# 与 MARS-Prompt.md 节点章节逐条对应
CONTRACTS: Mapping[str, NodeContract] = MappingProxyType(
    {
        "user": NodeContract(
            node="user",
            optional=("initial_prompt", "optimization_goal"),
            writes=("initial_prompt", "optimization_goal"),
        ),
        "planner": NodeContract(
            node="planner",
            required=("initial_prompt", "optimization_goal"),
            optional=("optimized_prompt", "subtasks"),
            writes=("working_prompt", "subtasks"),
        ),
        "teacher": NodeContract(
            node="teacher",
            required=("working_prompt", "subtasks"),
            optional=(
                "questions",
                "heuristic_score",
                "execution_score",
                "initial_prompt",
                "optimized_prompt",
                "optimization_goal",
            ),
            writes=("questions",),
        ),
        "student": NodeContract(
            node="student",
            required=("working_prompt", "optimization_goal", "questions"),
            optional=("subtasks",),
            writes=("optimized_prompt",),
        ),
        "critic": NodeContract(
            node="critic",
            required=("optimized_prompt", "optimization_goal", "subtasks", "questions"),
            optional=("working_prompt", "heuristic_score", "execution_score"),
            writes=(
                "subtasks",
                "questions",
                "heuristic_score",
                "execution_score",
                "tsc_count",
            ),
            side_effect_writes=("working_prompt", "optimized_prompt"),
            route_key="route_critic",
        ),
        "target": NodeContract(
            node="target",
            required=("optimized_prompt", "performance_criteria", "tsc_count", "m_count"),
            route_key="route_target",
        ),
        "output": NodeContract(
            node="output",
            required=("optimized_prompt",),
            writes=("report_md",),
        ),
        "manager": NodeContract(
            node="manager",
            required=(
                "optimized_prompt",
                "performance_criteria",
                "tsc_count",
                "m_count",
                "working_prompt",
                "subtasks",
                "questions",
                "heuristic_score",
                "execution_score",
            ),
            writes=("m_count",),
            side_effect_writes=(
                "working_prompt",
                "optimized_prompt",
                "subtasks",
                "questions",
                "heuristic_score",
                "execution_score",
                "tsc_count",
            ),
            route_key="route_manager",
        ),
    }
)

assert set(CONTRACTS) == set(NODE_NAMES)  # 内部不变量


@dataclass
class NodeSession:
    """一次节点执行的可注入上下文。"""

    issues: tuple[StateIssue, ...]
    clock: Clock
    idgen: IdGenerator
    started_at: datetime
    started_monotonic: float


def configurable(config: RunnableConfig) -> Mapping[str, Any]:
    """安全读取 configurable 字典。"""
    value = config.get("configurable")
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def session_of(config: RunnableConfig) -> NodeSession:
    """取出装饰器注入的节点会话。"""
    value = configurable(config).get("_session")
    if not isinstance(value, NodeSession):
        raise CodingContractError("缺少节点会话上下文")
    return value


@dataclass(frozen=True)
class LoopLimits:
    """单次运行的循环上限；未注入时回落到文档默认值。"""

    tsc_max: int = TSC_MAX
    m_max: int = M_MAX


def loop_limits(config: RunnableConfig) -> LoopLimits:
    """读取运行级上限配置，非法值回落到默认值。"""
    raw = configurable(config)
    tsc = raw.get("tsc_max")
    m = raw.get("m_max")
    return LoopLimits(
        tsc_max=tsc if isinstance(tsc, int) and not isinstance(tsc, bool) and tsc > 0 else TSC_MAX,
        m_max=m if isinstance(m, int) and not isinstance(m, bool) and m > 0 else M_MAX,
    )


def node_llm_config(config: RunnableConfig, node: str) -> NodeLLMConfig:
    """优先使用运行注入的节点配置，缺失时回退环境配置。"""
    configs = configurable(config).get("node_configs")
    if isinstance(configs, dict):
        value = configs.get(node)
        if isinstance(value, NodeLLMConfig):
            return value
        if value is not None:
            return NodeLLMConfig.model_validate(value)
    return default_node_config(node)


def _allowed_keys(contract: NodeContract) -> set[str]:
    allowed = set(contract.writes) | set(contract.side_effect_writes) | {"trace"}
    if contract.route_key is not None:
        allowed.add(contract.route_key)
    return allowed


def _ordered(keys: Sequence[str]) -> list[str]:
    """按文档业务字段顺序输出，便于快照比对。"""
    order = {field: index for index, field in enumerate(BUSINESS_FIELDS)}
    return sorted(keys, key=lambda key: order.get(key, len(order)))


def make_trace(
    session: NodeSession,
    *,
    node: str,
    summary: str,
    writes: Sequence[str],
    side_effects: Sequence[str] = (),
    extra_issues: Sequence[StateIssue] = (),
    model: str | None = None,
    prompt_version: str | None = None,
    human_intervention: bool = False,
    original_route: str | None = None,
    new_route: str | None = None,
    operator: str | None = None,
) -> NodeTrace:
    """构造唯一 trace；包含问题码、写入键、耗时与模型信息。"""
    duration_ms = max(0.0, session.clock.monotonic() - session.started_monotonic) * 1000
    trace: NodeTrace = {
        "node": node,
        "started_at": session.started_at.isoformat(),
        "duration_ms": round(duration_ms, 3),
        "model": model,
        "prompt_version": prompt_version,
        "issues": [issue.to_dict() for issue in (*session.issues, *extra_issues)],
        "writes": _ordered(writes),
        "side_effects": list(side_effects),
        "summary": summary,
    }
    if human_intervention:
        trace["human_intervention"] = True
        trace["original_route"] = original_route
        trace["new_route"] = new_route
        trace["operator"] = operator
        trace["at"] = session.clock.now().isoformat()
    return trace


def _make_session(
    issues: list[StateIssue],
    config: RunnableConfig,
) -> tuple[NodeSession, RunnableConfig]:
    """注入时钟、id 生成器与会话上下文。"""
    raw_config = dict(config)
    inner_configurable = dict(configurable(config))
    injected_clock = inner_configurable.get("clock")
    resolved_clock = cast(Clock, injected_clock) if injected_clock is not None else SystemClock()
    injected_idgen = inner_configurable.get("id_generator")
    session = NodeSession(
        issues=tuple(issues),
        clock=resolved_clock,
        idgen=(
            cast(IdGenerator, injected_idgen)
            if injected_idgen is not None
            else SequentialIdGenerator()
        ),
        started_at=resolved_clock.now(),
        started_monotonic=resolved_clock.monotonic(),
    )
    inner_configurable["_session"] = session
    raw_config["configurable"] = inner_configurable
    return session, cast(RunnableConfig, raw_config)


def _assert_contract(
    contract: NodeContract,
    state: GraphState,
    before: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """校验原子更新、只读字段与写入白名单。"""
    node = contract.node
    if dict(state) != before:
        raise CodingContractError(f"{node}: 禁止原地修改状态")
    if "performance_criteria" in result:
        raise CodingContractError(f"{node}: performance_criteria 为只读")
    extra = set(result) - _allowed_keys(contract)
    if extra:
        raise CodingContractError(f"{node}: 越界写入 {sorted(extra)}")
    traces = result.get("trace")
    if not isinstance(traces, list) or len(traces) != 1:
        raise CodingContractError(f"{node}: 必须追加恰好一条 trace")


def _execute(
    contract: NodeContract,
    fn: NodeFn,
    state: GraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    before = copy.deepcopy(dict(state))
    issues = validate_state(state, required=contract.required, optional=contract.optional)
    fatal = fatal_issues(issues)
    if fatal:
        raise FatalStateError(contract.node, fatal)
    _, inner_config = _make_session(issues, config)
    result = fn(state, inner_config)
    _assert_contract(contract, state, before, result)
    return result


def node_contract(
    *,
    node: str,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    writes: tuple[str, ...] = (),
    side_effect_writes: tuple[str, ...] = (),
    route_key: str | None = None,
) -> Callable[[NodeFn], NodeFn]:
    """包装节点：校验 → 执行 → 契约检查；1 级错误直接抛出不写入。"""

    contract = NodeContract(
        node=node,
        required=required,
        optional=optional,
        writes=writes,
        side_effect_writes=side_effect_writes,
        route_key=route_key,
    )
    declared = CONTRACTS.get(node)
    if declared is not None and contract != declared:
        raise CodingContractError(f"{node}: 节点声明与 CONTRACTS 不一致")

    def _decorator(fn: NodeFn) -> NodeFn:
        def _wrapper(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
            return _execute(contract, fn, state, config)

        return _wrapper

    return _decorator

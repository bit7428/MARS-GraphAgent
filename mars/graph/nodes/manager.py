"""Manager 节点：缺陷归属判定、回退清理与 M 循环计数。"""

from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import (
    LoopLimits,
    NodeSession,
    loop_limits,
    make_trace,
    node_contract,
    session_of,
)
from mars.graph.nodes.context import (
    call_structured,
    format_criteria,
    format_questions,
    format_score,
    format_subtasks,
    truncate,
)
from mars.graph.state.errors import (
    E2_LLM_FAILED,
    E2_MANAGER_ROUTE,
    LLMError,
    StateIssue,
)
from mars.graph.state.schema import GraphState

ManagerTarget = Literal["user", "planner", "teacher"]


class _ManagerOutput(BaseModel):
    """LLM 只判定缺陷归属，优先级由代码执行。"""

    user_defect: bool = False
    planner_defect: bool = False
    teacher_defect: bool = False
    reason: str = Field(default="")


@node_contract(
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
)
def run_manager(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Manager：按 User > Planner > Teacher 选择唯一回退边并清理状态。

    接收：全局状态。
    更新：11.；清理动作与计数递增合并为一次更新。
    报错：缺失 2/3/5/6/7/8/9/10/11 为 1 级；格式不规范为 2 级。
    """
    session = session_of(config)
    limits = loop_limits(config)
    if state["m_count"] >= limits.m_max:
        return _force_output(session, state, limits)

    target, extra, model, prompt_version = _choose_target(state, config, limits)
    update, side_effects = _cleanup_for(state, target)
    update["m_count"] = state["m_count"] + 1
    update["route_manager"] = target
    summary = messages.MANAGER_ROLLBACK.format(
        target=target,
        count=update["m_count"],
        maximum=limits.m_max,
    )
    trace = make_trace(
        session,
        node="manager",
        summary=summary,
        writes=("m_count",),
        side_effects=side_effects,
        extra_issues=extra,
        model=model,
        prompt_version=prompt_version,
    )
    update["trace"] = [trace]
    return update


def _force_output(
    session: NodeSession,
    state: GraphState,
    limits: LoopLimits,
) -> dict[str, Any]:
    trace = make_trace(
        session,
        node="manager",
        summary=messages.MANAGER_FORCE_OUTPUT.format(
            count=state["m_count"],
            maximum=limits.m_max,
        ),
        writes=("m_count",),
        side_effects=["force_output"],
    )
    return {"m_count": state["m_count"], "route_manager": "output", "trace": [trace]}


def _choose_target(
    state: GraphState,
    config: RunnableConfig,
    limits: LoopLimits,
) -> tuple[ManagerTarget, list[StateIssue], str | None, str | None]:
    body = (
        f"【初始提示词】\n{truncate(state['initial_prompt'])}\n\n"
        f"【优化方向及目的】\n{truncate(state['optimization_goal'])}\n\n"
        f"【待优化提示词】\n{truncate(state['working_prompt'])}\n\n"
        f"【已优化提示词】\n{truncate(state['optimized_prompt'])}\n\n"
        f"【子任务列表】\n{format_subtasks(state['subtasks'])}\n\n"
        f"【启发式提问列表】\n{format_questions(state['questions'])}\n\n"
        f"{format_score('启发得分及摘要', state['heuristic_score'])}\n\n"
        f"{format_score('执行得分及摘要', state['execution_score'])}\n\n"
        f"【性能指标】\n{format_criteria(state['performance_criteria'])}\n\n"
        f"【TSC 循环次数】{state['tsc_count']}／{limits.tsc_max}\n"
        f"【M 循环次数】{state['m_count']}／{limits.m_max}\n\n"
        "验收未通过。请判定缺陷归属后按系统提示词约定输出 JSON。"
    )
    try:
        result = call_structured(config, node="manager", body=body, schema=_ManagerOutput)
    except LLMError as exc:
        return (
            "teacher",
            [
                StateIssue(
                    code=E2_LLM_FAILED,
                    level=2,
                    field=None,
                    message=messages.MANAGER_LLM_FAILED.format(error=type(exc).__name__),
                ),
                StateIssue(
                    code=E2_MANAGER_ROUTE,
                    level=2,
                    field="route_manager",
                    message=messages.MANAGER_DEFAULT_ROUTE,
                ),
            ],
            None,
            None,
        )
    target: ManagerTarget
    if result.data.user_defect:
        target = "user"
    elif result.data.planner_defect:
        target = "planner"
    else:
        target = "teacher"
    return target, [], result.model, result.prompt_version


def _cleanup_for(state: GraphState, target: ManagerTarget) -> tuple[dict[str, Any], list[str]]:
    """按文档回退规则清理；清理与计数在同一字典返回。"""
    if target == "user":
        update: dict[str, Any] = {
            "working_prompt": "",
            "optimized_prompt": "",
            "subtasks": [],
            "questions": [],
            "heuristic_score": None,
            "execution_score": None,
            "tsc_count": 0,
        }
        return update, ["clear:2/3/5/6/7/8", "reset:tsc_count"]
    if target == "planner":
        # 文档未要求清空 2，保留供 Planner 参考
        update = {
            "optimized_prompt": "",
            "questions": [],
            "heuristic_score": None,
            "execution_score": None,
            "tsc_count": 0,
        }
        return update, ["clear:3/6/7/8", "keep:subtasks", "reset:tsc_count"]
    update = {
        "working_prompt": state["optimized_prompt"],
        "optimized_prompt": "",
    }
    return update, ["working_prompt<-optimized_prompt", "optimized_prompt=空"]

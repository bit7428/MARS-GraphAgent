"""User 节点：非 LLM，接收用户初始化或补充输入。"""

from collections.abc import Mapping
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from mars import messages
from mars.graph.contract import configurable, make_trace, node_contract, session_of
from mars.graph.state.errors import E2_MISSING, StateIssue
from mars.graph.state.schema import GraphState


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _apply(existing: str, incoming: str, mode: str) -> str:
    if not incoming:
        return existing
    if mode == "replace" or not existing:
        return incoming
    return f"{existing}\n\n{incoming}"


@node_contract(
    node="user",
    optional=("initial_prompt", "optimization_goal"),
    writes=("initial_prompt", "optimization_goal"),
)
def run_user(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """User：接收并确认 1/4。

    接收：无（直接对接用户）｜1.3.4.5.（经 Manager 传入）。
    更新：1.4.。
    报错：首次初始化无报错；经 Manager 传入时 1/4 缺失或为空记 2 级。
    """
    supplement = configurable(config).get("user_supplement")
    mode = "append"
    initial = _text(state.get("initial_prompt"))
    goal = _text(state.get("optimization_goal"))
    if isinstance(supplement, Mapping):
        record = cast(Mapping[str, object], supplement)
        mode = _text(record.get("mode")) or "append"
        initial = _apply(initial, _text(record.get("initial_prompt")), mode)
        goal = _apply(goal, _text(record.get("optimization_goal")), mode)

    extra: list[StateIssue] = []
    if not initial or not goal:
        missing_field = None
        if not initial and not goal:
            missing_field = None
        elif not initial:
            missing_field = "initial_prompt"
        else:
            missing_field = "optimization_goal"
        extra.append(
            StateIssue(
                code=E2_MISSING[missing_field or "initial_prompt"],
                level=2,
                field=missing_field,
                message=messages.USER_MISSING_INPUT,
            )
        )

    session = session_of(config)
    summary = messages.USER_RECEIVED if not extra else messages.USER_INCOMPLETE
    trace = make_trace(
        session,
        node="user",
        summary=summary,
        writes=("initial_prompt", "optimization_goal"),
        extra_issues=extra,
    )
    return {"initial_prompt": initial, "optimization_goal": goal, "trace": [trace]}

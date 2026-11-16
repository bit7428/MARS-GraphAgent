"""Target 节点：按性能指标做最终验收，只写路由键。"""

from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import make_trace, node_contract, session_of
from mars.graph.nodes.context import call_structured, format_criteria, truncate
from mars.graph.state.errors import (
    E2_TARGET_UNDECIDABLE,
    LLMError,
    StateIssue,
)
from mars.graph.state.schema import GraphState

TargetRoute = Literal["output", "manager"]


class _CriterionResult(BaseModel):
    name: str = Field(min_length=1)
    passed: bool
    reason: str = ""


class _TargetOutput(BaseModel):
    criteria: list[_CriterionResult] = Field(default_factory=list)
    passed: bool
    reason: str = ""


@node_contract(
    node="target",
    required=("optimized_prompt", "performance_criteria", "tsc_count", "m_count"),
    route_key="route_target",
)
def run_target(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Target：验收 3. 是否满足 9.，不修改 3/9。

    接收：3.9.10.11.。
    更新：无业务字段；生成 route_target 作为条件边依据。
    报错：缺失 3/9/10/11 为 1 级；验收结论无法生成为 2 级并默认 manager。
    """
    session = session_of(config)
    route, summary, extra, model, prompt_version = _evaluate(state, config)
    trace = make_trace(
        session,
        node="target",
        summary=summary,
        writes=(),
        extra_issues=extra,
        model=model,
        prompt_version=prompt_version,
    )
    return {"route_target": route, "trace": [trace]}


def _evaluate(
    state: GraphState,
    config: RunnableConfig,
) -> tuple[TargetRoute, str, list[StateIssue], str | None, str | None]:
    body = (
        f"【已优化提示词】\n{truncate(state['optimized_prompt'])}\n\n"
        f"【性能指标】\n{format_criteria(state['performance_criteria'])}\n\n"
        f"【TSC 循环次数】{state['tsc_count']}\n"
        f"【M 循环次数】{state['m_count']}\n\n"
        "请按系统提示词约定输出 JSON，并逐项给出是否达标。"
    )
    try:
        result = call_structured(config, node="target", body=body, schema=_TargetOutput)
    except LLMError as exc:
        return (
            "manager",
            messages.TARGET_UNDECIDABLE,
            [
                StateIssue(
                    code=E2_TARGET_UNDECIDABLE,
                    level=2,
                    field=None,
                    message=messages.TARGET_LLM_FAILED.format(error=type(exc).__name__),
                )
            ],
            None,
            None,
        )

    expected = [item["name"] for item in state["performance_criteria"]]
    verdict = {item.name: item.passed for item in result.data.criteria}
    missing = [name for name in expected if name not in verdict]
    if missing:
        return (
            "manager",
            messages.TARGET_UNDECIDABLE,
            [
                StateIssue(
                    code=E2_TARGET_UNDECIDABLE,
                    level=2,
                    field="performance_criteria",
                    message=messages.TARGET_MISSING_CRITERIA.format(names=",".join(missing)),
                )
            ],
            result.model,
            result.prompt_version,
        )
    passed = result.data.passed and all(verdict[name] for name in expected)
    return (
        "output" if passed else "manager",
        messages.TARGET_PASS if passed else messages.TARGET_FAIL,
        [],
        result.model,
        result.prompt_version,
    )

"""Student 节点：根据待优化提示词、目标与提问生成已优化提示词。"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import make_trace, node_contract, session_of
from mars.graph.nodes.context import (
    call_structured,
    format_questions,
    format_subtasks,
    truncate,
)
from mars.graph.state.errors import E2_LLM_FAILED, LLMError, StateIssue
from mars.graph.state.schema import GraphState


class _StudentOutput(BaseModel):
    optimized_prompt: str = Field(min_length=1)


@node_contract(
    node="student",
    required=("working_prompt", "optimization_goal", "questions"),
    optional=("subtasks",),
    writes=("optimized_prompt",),
)
def run_student(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Student：根据 2/4/6 生成 3.，不直接修改输入。

    接收：2.4.6.；5.（待选）。
    更新：3.。
    报错：缺失 2/4/6 为 1 级；缺失 5 为 2 级；格式不规范为 2 级。
    """
    session = session_of(config)
    questions = list(state["questions"])
    subtasks = list(state.get("subtasks") or [])
    body = (
        f"【待优化提示词】\n{truncate(state['working_prompt'])}\n\n"
        f"【优化方向及目的】\n{truncate(state['optimization_goal'])}\n\n"
        f"【启发式提问列表】\n{format_questions(questions)}\n\n"
        f"【子任务列表（参考）】\n{format_subtasks(subtasks)}\n\n"
        "请按系统提示词约定输出 JSON。"
    )
    extra: list[StateIssue] = []
    model: str | None = None
    prompt_version: str | None = None
    optimized = state["working_prompt"]
    try:
        result = call_structured(config, node="student", body=body, schema=_StudentOutput)
        model = result.model
        prompt_version = result.prompt_version
        optimized = result.data.optimized_prompt
    except LLMError as exc:
        extra.append(
            StateIssue(
                code=E2_LLM_FAILED,
                level=2,
                field="optimized_prompt",
                message=messages.STUDENT_LLM_FAILED.format(error=type(exc).__name__),
            )
        )

    trace = make_trace(
        session,
        node="student",
        summary=messages.STUDENT_SUMMARY if model else messages.STUDENT_FALLBACK,
        writes=("optimized_prompt",),
        extra_issues=extra,
        model=model,
        prompt_version=prompt_version,
    )
    return {"optimized_prompt": optimized, "trace": [trace]}

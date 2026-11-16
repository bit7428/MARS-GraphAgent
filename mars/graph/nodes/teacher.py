"""Teacher 节点：追加苏格拉底式启发提问。"""

from collections.abc import Sequence
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import make_trace, node_contract, session_of
from mars.graph.nodes.context import (
    call_structured,
    format_questions,
    format_score,
    format_subtasks,
    low_dimension_hint,
    truncate,
)
from mars.graph.state.errors import E2_LLM_FAILED, LLMError, StateIssue
from mars.graph.state.ids import next_id
from mars.graph.state.models import Question, Subtask
from mars.graph.state.schema import GraphState


class _QuestionDraft(BaseModel):
    content: str = Field(min_length=1)
    target_task_id: str | None = None


class _TeacherOutput(BaseModel):
    questions: list[_QuestionDraft] = Field(default_factory=list)


@node_contract(
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
)
def run_teacher(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Teacher：追加 6. 提问，不覆盖既有项。

    接收：2.5.；6.7.8.（Critic 唤醒）；1.3.4.（Manager 唤醒）。
    更新：6.。
    报错：缺失 2/5 为 1 级；循环中缺 3/6/7/8 为 2 级；格式不规范为 2 级。
    """
    session = session_of(config)
    subtasks = list(state["subtasks"])
    existing = list(state.get("questions") or [])
    body = (
        f"【待优化提示词】\n{truncate(state['working_prompt'])}\n\n"
        f"【子任务列表】\n{format_subtasks(subtasks)}\n\n"
        f"【已有提问】\n{format_questions(existing)}\n\n"
        f"{format_score('启发得分及摘要', state.get('heuristic_score'))}\n\n"
        f"{format_score('执行得分及摘要', state.get('execution_score'))}\n\n"
        f"【聚焦提示】{low_dimension_hint(state)}\n\n"
        f"【初始提示词（参考）】\n{truncate(state.get('initial_prompt') or '缺失')}\n\n"
        f"【优化方向及目的（参考）】\n{truncate(state.get('optimization_goal') or '缺失')}\n\n"
        f"【已优化提示词（参考）】\n{truncate(state.get('optimized_prompt') or '缺失')}\n\n"
        "请按系统提示词约定输出 JSON。"
    )
    extra: list[StateIssue] = []
    model: str | None = None
    prompt_version: str | None = None
    created: list[Question] = []
    try:
        result = call_structured(config, node="teacher", body=body, schema=_TeacherOutput)
        model = result.model
        prompt_version = result.prompt_version
        created = _build_questions(subtasks, existing, result.data.questions)
    except LLMError as exc:
        extra.append(
            StateIssue(
                code=E2_LLM_FAILED,
                level=2,
                field="questions",
                message=messages.TEACHER_LLM_FAILED.format(error=type(exc).__name__),
            )
        )

    questions = [*existing, *created]
    summary = (
        messages.TEACHER_SUMMARY.format(count=len(created)) if created else messages.TEACHER_EMPTY
    )
    trace = make_trace(
        session,
        node="teacher",
        summary=summary,
        writes=("questions",),
        extra_issues=extra,
        model=model,
        prompt_version=prompt_version,
    )
    return {"questions": questions, "trace": [trace]}


def _build_questions(
    subtasks: Sequence[Subtask],
    existing: list[Question],
    drafts: list[_QuestionDraft],
) -> list[Question]:
    """追加新 id，保留全部既有项（含 resolved / dropped）。"""
    task_ids = {item["id"] for item in subtasks}
    ids = [item["id"] for item in existing]
    built: list[Question] = []
    for draft in drafts:
        text = draft.content.strip()
        if not text:
            continue
        new_id = next_id("q", [*ids, *[item["id"] for item in built]])
        target = draft.target_task_id if draft.target_task_id in task_ids else None
        built.append(
            cast(
                Question,
                {
                    "id": new_id,
                    "content": text,
                    "target_task_id": target,
                    "status": "open",
                    "score": 0,
                },
            )
        )
    return built

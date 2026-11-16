"""Planner 节点：生成第一版待优化提示词与子任务列表。"""

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import make_trace, node_contract, session_of
from mars.graph.nodes.context import (
    call_structured,
    format_subtasks,
    truncate,
)
from mars.graph.state.errors import E2_LLM_FAILED, LLMError, StateIssue
from mars.graph.state.ids import next_id
from mars.graph.state.models import Subtask
from mars.graph.state.schema import GraphState


class _SubtaskDraft(BaseModel):
    content: str = Field(min_length=1)


class _PlannerOutput(BaseModel):
    working_prompt: str = Field(min_length=1)
    subtasks: list[_SubtaskDraft] = Field(default_factory=list)


@node_contract(
    node="planner",
    required=("initial_prompt", "optimization_goal"),
    conditional_optional=(
        ("optimized_prompt", "tsc"),
        ("subtasks", "tsc"),
    ),
    writes=("working_prompt", "subtasks"),
)
def run_planner(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Planner：生成 2. 并追加 5.。

    接收：1.4.｜3.5.（经 Manager 传入）。
    更新：2.5.。
    报错：缺失 1/4 为 1 级；10/11 非 0 且缺 3/5 为 2 级；格式不规范为 2 级。
    """
    session = session_of(config)
    existing = list(state.get("subtasks") or [])
    body = (
        f"【初始提示词】\n{truncate(state['initial_prompt'])}\n\n"
        f"【优化方向及目的】\n{truncate(state['optimization_goal'])}\n\n"
        f"【已优化提示词（参考）】\n{truncate(state.get('optimized_prompt') or '缺失')}\n\n"
        f"【现有子任务（参考）】\n{format_subtasks(existing)}\n\n"
        "请按系统提示词约定输出 JSON。"
    )
    extra: list[StateIssue] = []
    model: str | None = None
    prompt_version: str | None = None
    working_prompt = state["initial_prompt"]
    created: list[Subtask] = []
    try:
        result = call_structured(config, node="planner", body=body, schema=_PlannerOutput)
        model = result.model
        prompt_version = result.prompt_version
        working_prompt = result.data.working_prompt
        created = _build_subtasks(existing, [item.content for item in result.data.subtasks])
    except LLMError as exc:
        extra.append(
            StateIssue(
                code=E2_LLM_FAILED,
                level=2,
                field="working_prompt",
                message=messages.PLANNER_LLM_FAILED.format(error=type(exc).__name__),
            )
        )

    subtasks = [*existing, *created]
    summary = messages.PLANNER_SUMMARY.format(count=len(created))
    trace = make_trace(
        session,
        node="planner",
        summary=summary,
        writes=("working_prompt", "subtasks"),
        extra_issues=extra,
        model=model,
        prompt_version=prompt_version,
    )
    return {"working_prompt": working_prompt, "subtasks": subtasks, "trace": [trace]}


def _build_subtasks(existing: list[Subtask], contents: list[str]) -> list[Subtask]:
    """整表替换语义下仍保持 append-only：已存在项不删除，新项使用新 id。"""
    ids = [item["id"] for item in existing]
    built: list[Subtask] = []
    for content in contents:
        text = content.strip()
        if not text:
            continue
        new_id = next_id("s", [*ids, *[item["id"] for item in built]])
        built.append(
            cast(
                Subtask,
                {
                    "id": new_id,
                    "content": text,
                    "source": "planner",
                    "status": "pending",
                    "score": 0,
                },
            )
        )
    return built

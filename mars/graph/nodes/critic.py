"""Critic 节点：打分、划去完成项并决定 TSC 回路或验收。"""

from dataclasses import dataclass
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from mars import messages
from mars.graph.contract import LoopLimits, loop_limits, make_trace, node_contract, session_of
from mars.graph.nodes.context import (
    call_structured,
    format_questions,
    format_score,
    format_subtasks,
    truncate,
)
from mars.graph.state.constants import QUESTION_RESOLVED_THRESHOLD, SUBTASK_DONE_THRESHOLD
from mars.graph.state.errors import (
    E2_LLM_FAILED,
    E2_LLM_SCHEMA,
    LLMError,
    StateIssue,
)
from mars.graph.state.models import Question, ScoreDetail, Subtask
from mars.graph.state.schema import GraphState


class _ItemScore(BaseModel):
    id: str
    score: int = Field(ge=0, le=100)


class _ScoreDetailOut(BaseModel):
    score: int = Field(ge=0, le=100)
    dimensions: dict[str, int] = Field(default_factory=dict)
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class _CriticOutput(BaseModel):
    subtask_scores: list[_ItemScore] = Field(default_factory=list)
    question_scores: list[_ItemScore] = Field(default_factory=list)
    heuristic: _ScoreDetailOut
    execution: _ScoreDetailOut
    passed: bool
    reason: str = ""


@dataclass
class _Evaluation:
    """一次 Critic 评审的可合并结果。"""

    subtasks: list[Subtask]
    questions: list[Question]
    heuristic: ScoreDetail | None
    execution: ScoreDetail | None
    llm_passed: bool
    extra: list[StateIssue]
    model: str | None
    prompt_version: str | None


@node_contract(
    node="critic",
    required=("optimized_prompt", "optimization_goal", "subtasks", "questions"),
    conditional_optional=(
        ("working_prompt", "tsc"),
        ("heuristic_score", "tsc"),
        ("execution_score", "tsc"),
    ),
    writes=(
        "subtasks",
        "questions",
        "heuristic_score",
        "execution_score",
        "tsc_count",
    ),
    side_effect_writes=("working_prompt", "optimized_prompt"),
    route_key="route_critic",
)
def run_critic(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Critic：更新 5/6/7/8/10 并路由到 Teacher 或 Target。

    接收：3.4.5.6.；2.7.8.（待选）。
    更新：5.6.7.8.10.；不通过且未超限时 2←3、3 置空并 10+1（同一次更新）。
    报错：缺失 3/4/5/6 为 1 级；缺失 2/7/8 为 2 级；格式不规范为 2 级。
    """
    session = session_of(config)
    limits = loop_limits(config)
    evaluation = _evaluate(state, config)
    update, side_effects, summary = _decide(
        state,
        evaluation.subtasks,
        evaluation.questions,
        evaluation.llm_passed,
        limits,
    )
    update["heuristic_score"] = evaluation.heuristic
    update["execution_score"] = evaluation.execution
    trace = make_trace(
        session,
        node="critic",
        summary=summary,
        writes=(
            "subtasks",
            "questions",
            "heuristic_score",
            "execution_score",
            "tsc_count",
        ),
        side_effects=side_effects,
        extra_issues=evaluation.extra,
        model=evaluation.model,
        prompt_version=evaluation.prompt_version,
    )
    update["trace"] = [trace]
    return update


def _evaluate(state: GraphState, config: RunnableConfig) -> _Evaluation:
    subtasks: list[Subtask] = [{**item} for item in state["subtasks"]]
    questions: list[Question] = [{**item} for item in state["questions"]]
    body = (
        f"【已优化提示词】\n{truncate(state['optimized_prompt'])}\n\n"
        f"【优化方向及目的】\n{truncate(state['optimization_goal'])}\n\n"
        f"【子任务列表】\n{format_subtasks(subtasks)}\n\n"
        f"【启发式提问列表】\n{format_questions(questions)}\n\n"
        f"【待优化提示词（参考）】\n{truncate(state.get('working_prompt') or '缺失')}\n\n"
        f"{format_score('启发得分及摘要', state.get('heuristic_score'))}\n\n"
        f"{format_score('执行得分及摘要', state.get('execution_score'))}\n\n"
        "请按系统提示词约定输出 JSON。"
    )
    try:
        result = call_structured(config, node="critic", body=body, schema=_CriticOutput)
    except LLMError as exc:
        return _Evaluation(
            subtasks=subtasks,
            questions=questions,
            heuristic=state.get("heuristic_score"),
            execution=state.get("execution_score"),
            llm_passed=False,
            extra=[
                StateIssue(
                    code=E2_LLM_FAILED,
                    level=2,
                    field=None,
                    message=messages.CRITIC_LLM_FAILED.format(error=type(exc).__name__),
                )
            ],
            model=None,
            prompt_version=None,
        )

    sub_scores = {item.id: item.score for item in result.data.subtask_scores}
    question_scores = {item.id: item.score for item in result.data.question_scores}
    extra = _score_issues(subtasks, questions, sub_scores, question_scores)
    _apply_subtask_scores(subtasks, sub_scores)
    _apply_question_scores(questions, question_scores)
    return _Evaluation(
        subtasks=subtasks,
        questions=questions,
        heuristic=_clean_detail(
            result.data.heuristic,
            fallback=[item["id"] for item in questions]
            or [item["id"] for item in subtasks]
            or ["none"],
        ),
        execution=_clean_detail(result.data.execution, fallback=[]),
        llm_passed=result.data.passed,
        extra=extra,
        model=result.model,
        prompt_version=result.prompt_version,
    )


def _score_issues(
    subtasks: list[Subtask],
    questions: list[Question],
    sub_scores: dict[str, int],
    question_scores: dict[str, int],
) -> list[StateIssue]:
    known = {item["id"] for item in [*subtasks, *questions]}
    unknown = [item_id for item_id in {**sub_scores, **question_scores} if item_id not in known]
    missing = [
        item["id"]
        for item in [*subtasks, *questions]
        if item["id"] not in sub_scores and item["id"] not in question_scores
    ]
    issues: list[StateIssue] = []
    if unknown:
        issues.append(
            StateIssue(
                code=E2_LLM_SCHEMA,
                level=2,
                field=None,
                message=messages.CRITIC_UNKNOWN_IDS.format(ids=",".join(unknown[:5])),
            )
        )
    if missing:
        issues.append(
            StateIssue(
                code=E2_LLM_SCHEMA,
                level=2,
                field="questions",
                message=messages.CRITIC_MISSING_SCORES.format(ids=",".join(missing[:5])),
            )
        )
    return issues


def _decide(
    state: GraphState,
    subtasks: list[Subtask],
    questions: list[Question],
    llm_passed: bool,
    limits: LoopLimits,
) -> tuple[dict[str, Any], list[str], str]:
    pending = any(item["status"] == "pending" for item in subtasks)
    unresolved = any(item["status"] == "open" for item in questions)
    passed = llm_passed and not pending and not unresolved
    update: dict[str, Any] = {
        "subtasks": subtasks,
        "questions": questions,
        "tsc_count": state["tsc_count"],
    }
    if passed:
        update["route_critic"] = "target"
        return update, [], messages.CRITIC_PASS
    if state["tsc_count"] >= limits.tsc_max:
        update["route_critic"] = "target"
        return (
            update,
            [],
            messages.CRITIC_TSC_OVER.format(count=state["tsc_count"], maximum=limits.tsc_max),
        )
    update["route_critic"] = "teacher"
    update["working_prompt"] = state["optimized_prompt"]
    update["optimized_prompt"] = ""
    update["tsc_count"] = state["tsc_count"] + 1
    return (
        update,
        ["working_prompt<-optimized_prompt", "optimized_prompt=空", "tsc_count+1"],
        messages.CRITIC_LOOP.format(count=update["tsc_count"], maximum=limits.tsc_max),
    )


def _apply_subtask_scores(items: list[Subtask], scores: dict[str, int]) -> None:
    for item in items:
        if item["id"] not in scores:
            continue
        item["score"] = scores[item["id"]]
        if item["score"] > SUBTASK_DONE_THRESHOLD and item["status"] != "dropped":
            item["status"] = "dropped"


def _apply_question_scores(items: list[Question], scores: dict[str, int]) -> None:
    for item in items:
        if item["id"] not in scores:
            continue
        item["score"] = scores[item["id"]]
        if item["score"] > QUESTION_RESOLVED_THRESHOLD and item["status"] != "dropped":
            item["status"] = "dropped"


def _clean_detail(detail: _ScoreDetailOut, *, fallback: list[str]) -> ScoreDetail:
    return cast(
        ScoreDetail,
        {
            "score": detail.score,
            "dimensions": dict(detail.dimensions),
            "summary": detail.summary,
            "evidence": detail.evidence or fallback,
        },
    )

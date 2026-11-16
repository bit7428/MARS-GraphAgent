"""测试用状态构造器。"""

from typing import Any, cast

from mars.graph.state.models import (
    PerformanceCriterion,
    Question,
    ScoreDetail,
    Subtask,
)
from mars.graph.state.schema import GraphState


def score(score_value: int = 80, *, dimensions: dict[str, int] | None = None) -> ScoreDetail:
    return cast(
        ScoreDetail,
        {
            "score": score_value,
            "dimensions": dimensions or {"clarity": score_value},
            "summary": "分数变化原因",
            "evidence": ["q001"],
        },
    )


def subtask(item_id: str = "s001", *, status: str = "pending", value: int = 0) -> Subtask:
    return cast(
        Subtask,
        {
            "id": item_id,
            "content": f"任务 {item_id}",
            "source": "planner",
            "status": status,
            "score": value,
        },
    )


def question(item_id: str = "q001", *, status: str = "open", value: int = 0) -> Question:
    return cast(
        Question,
        {
            "id": item_id,
            "content": f"提问 {item_id}",
            "target_task_id": "s001",
            "status": status,
            "score": value,
        },
    )


def criterion() -> PerformanceCriterion:
    return cast(
        PerformanceCriterion,
        {"name": "正确性", "threshold": 0.9, "comparator": "gte"},
    )


def base_state(**overrides: Any) -> GraphState:
    state: dict[str, Any] = {
        "initial_prompt": "初始提示词",
        "working_prompt": "待优化提示词",
        "optimized_prompt": "已优化提示词",
        "optimization_goal": "让提示词更清晰",
        "subtasks": [subtask()],
        "questions": [question()],
        "heuristic_score": score(),
        "execution_score": score(),
        "performance_criteria": [criterion()],
        "tsc_count": 0,
        "m_count": 0,
    }
    state.update(overrides)
    return cast(GraphState, state)


def without_state(*keys: str, **overrides: Any) -> GraphState:
    state = cast(dict[str, Any], base_state(**overrides))
    for key in keys:
        state.pop(key, None)
    return cast(GraphState, state)


def initial_state() -> GraphState:
    return cast(
        GraphState,
        {
            "initial_prompt": "初始提示词",
            "optimization_goal": "让提示词更清晰",
            "performance_criteria": [criterion()],
            "tsc_count": 0,
            "m_count": 0,
        },
    )

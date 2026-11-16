"""状态校验测试。"""

from typing import Any, cast

import pytest

from mars.graph.state.schema import GraphState
from mars.graph.state.validate import validate_state
from mars.tests.fixtures.states import base_state, without_state


def _codes(issues: list[Any]) -> list[str]:
    return [issue.code for issue in issues]


def test_required_missing_is_level_one() -> None:
    issues = validate_state(
        without_state("initial_prompt"),
        required=("initial_prompt", "optimization_goal"),
        optional=(),
    )
    assert issues[0].code == "E1-MISSING-INITIAL-PROMPT"
    assert issues[0].level == 1


def test_required_null_is_level_one() -> None:
    state = cast(GraphState, {"initial_prompt": None, "optimization_goal": "目标"})
    issues = validate_state(state, required=("initial_prompt",), optional=("optimization_goal",))
    assert "E1-MISSING-INITIAL-PROMPT" in _codes(issues)


def test_optional_missing_is_level_two() -> None:
    issues = validate_state(
        without_state("questions"),
        required=("initial_prompt",),
        optional=("questions",),
    )
    assert "E2-MISSING-QUESTIONS" in _codes(issues)
    assert all(issue.level == 2 for issue in issues)


def test_empty_list_is_present() -> None:
    issues = validate_state(
        base_state(subtasks=[]),
        required=("subtasks",),
        optional=(),
    )
    assert "E1-MISSING-SUBTASKS" not in _codes(issues)


def test_invalid_subtask_schema() -> None:
    state = cast(GraphState, {"subtasks": [{"id": "s001"}]})
    issues = validate_state(state, required=("subtasks",), optional=())
    assert "E2-SCHEMA-SUBTASK" in _codes(issues)


def test_invalid_question_schema() -> None:
    state = cast(
        GraphState,
        {"questions": [{"id": "q1", "content": "x", "status": "open", "score": 101}]},
    )
    issues = validate_state(state, required=("questions",), optional=())
    assert "E2-SCHEMA-QUESTION" in _codes(issues)


def test_empty_criteria_is_schema_error() -> None:
    issues = validate_state(
        base_state(performance_criteria=[]),
        required=("performance_criteria",),
        optional=(),
    )
    assert "E2-SCHEMA-PERFORMANCE-CRITERIA" in _codes(issues)


def test_conditional_missing_fields() -> None:
    state = without_state(
        "optimized_prompt",
        "subtasks",
        "questions",
        "heuristic_score",
        "execution_score",
        tsc_count=1,
    )
    issues = validate_state(state, required=(), optional=())
    codes = _codes(issues)
    assert "E2-CONDITIONAL-MISSING-OPTIMIZED-PROMPT" in codes
    assert "E2-CONDITIONAL-MISSING-SUBTASK" in codes
    assert "E2-CONDITIONAL-MISSING-QUESTION" in codes


def test_counter_rejects_bool_and_negative() -> None:
    issues = validate_state(
        cast(GraphState, {"tsc_count": True, "m_count": -1}),
        required=("tsc_count", "m_count"),
        optional=(),
    )
    codes = _codes(issues)
    assert codes.count("E2-SCHEMA-TSC-COUNT") == 1
    assert codes.count("E2-SCHEMA-M-COUNT") == 1


def test_invalid_route_key() -> None:
    state = cast(GraphState, {"route_critic": "student"})
    issues = validate_state(state, required=(), optional=())
    assert "E2-SCHEMA-ROUTE" in _codes(issues)


def test_unknown_field_is_flagged() -> None:
    state = cast(GraphState, {"unregistered": 1})
    issues = validate_state(state, required=(), optional=())
    assert "E2-UNKNOWN-STATE-FIELD" in _codes(issues)


def test_validation_is_pure() -> None:
    state = base_state()
    before = cast(dict[str, Any], state).copy()
    validate_state(state, required=("initial_prompt",), optional=())
    assert state == before


def _schema_codes(field: str, value: Any) -> list[str]:
    issues = validate_state(cast(GraphState, {field: value}), required=(field,), optional=())
    return _codes(issues)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-list",
        [1],
        [{"id": "", "content": "x", "status": "pending", "score": 0}],
        [
            {"id": "s1", "content": "x", "status": "pending", "score": 0},
            {"id": "s1", "content": "y", "status": "pending", "score": 0},
        ],
        [{"id": "s1", "content": "", "status": "pending", "score": 0}],
        [{"id": "s1", "content": "x", "status": "bad", "score": 0}],
        [{"id": "s1", "content": "x", "status": "pending", "score": 101}],
        [{"id": "s1", "content": "x", "status": "pending", "score": True}],
        [{"id": "s1", "content": "x", "status": "pending", "score": 0, "source": "bad"}],
    ],
)
def test_invalid_subtask_variants(value: Any) -> None:
    assert "E2-SCHEMA-SUBTASK" in _schema_codes("subtasks", value)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-list",
        [1],
        [{"id": "", "content": "x", "status": "open", "score": 0}],
        [
            {"id": "q1", "content": "x", "status": "open", "score": 0},
            {"id": "q1", "content": "y", "status": "open", "score": 0},
        ],
        [{"id": "q1", "content": "", "status": "open", "score": 0}],
        [{"id": "q1", "content": "x", "status": "bad", "score": 0}],
        [{"id": "q1", "content": "x", "status": "open", "score": -1}],
        [{"id": "q1", "content": "x", "status": "open", "score": 0, "target_task_id": 1}],
    ],
)
def test_invalid_question_variants(value: Any) -> None:
    assert "E2-SCHEMA-QUESTION" in _schema_codes("questions", value)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-dict",
        {"score": 101, "summary": "x", "evidence": ["q1"]},
        {"score": 80, "summary": "", "evidence": ["q1"]},
        {"score": 80, "summary": "x", "dimensions": [], "evidence": ["q1"]},
        {"score": 80, "summary": "x", "dimensions": {"a": "b"}, "evidence": ["q1"]},
        {"score": 80, "summary": "x", "evidence": "bad"},
        {"score": 80, "summary": "x", "evidence": []},
    ],
)
def test_invalid_heuristic_variants(value: Any) -> None:
    assert "E2-SCHEMA-HEURISTIC-SCORE" in _schema_codes("heuristic_score", value)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-list",
        [1],
        [{"name": "", "threshold": 1, "comparator": "gte"}],
        [{"name": "a", "threshold": True, "comparator": "gte"}],
        [{"name": "a", "threshold": 1, "comparator": "bad"}],
    ],
)
def test_invalid_criteria_variants(value: Any) -> None:
    assert "E2-SCHEMA-PERFORMANCE-CRITERIA" in _schema_codes("performance_criteria", value)


def test_empty_prompt_is_schema_error() -> None:
    assert "E2-SCHEMA-INITIAL-PROMPT" in _schema_codes("initial_prompt", "   ")

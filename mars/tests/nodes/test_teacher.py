"""Teacher 节点测试。"""

from mars.graph.nodes.teacher import run_teacher
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, question, score, without_state


def test_teacher_appends_questions_and_preserves_existing() -> None:
    adapter = ScriptedAdapter([{"questions": [{"content": "新提问", "target_task_id": "s001"}]}])
    result = state_invoke(run_teacher, base_state(), adapter)
    assert [item["id"] for item in result["questions"]] == ["q001", "q002"]
    assert result["questions"][0]["status"] == "open"
    assert result["questions"][1]["content"] == "新提问"


def test_teacher_preserves_resolved_and_dropped_items() -> None:
    state = base_state(
        questions=[question("q001", status="resolved"), question("q002", status="dropped")]
    )
    adapter = ScriptedAdapter([{"questions": [{"content": "追问"}]}])
    result = state_invoke(run_teacher, state, adapter)
    assert [item["id"] for item in result["questions"]] == ["q001", "q002", "q003"]
    assert result["questions"][0]["status"] == "resolved"
    assert result["questions"][1]["status"] == "dropped"


def test_teacher_focuses_low_dimensions() -> None:
    state = base_state(
        heuristic_score=score(40, dimensions={"clarity": 20, "depth": 80}),
        execution_score=score(50, dimensions={"coverage": 30}),
    )
    adapter = ScriptedAdapter([{"questions": []}])
    state_invoke(run_teacher, state, adapter)
    body = adapter.calls[0][-1]["content"]
    assert "clarity" in body
    assert "coverage" in body
    assert "聚焦提示" in body


def test_teacher_llm_failure_keeps_questions() -> None:
    result = state_invoke(run_teacher, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert [item["id"] for item in result["questions"]] == ["q001"]
    assert any(issue["code"] == "E2-LLM-FAILED" for issue in result["trace"][0]["issues"])


def test_teacher_missing_subtasks_is_fatal() -> None:
    try:
        state_invoke(run_teacher, without_state("subtasks"), ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-SUBTASKS"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")

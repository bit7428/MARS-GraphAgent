"""Student 节点测试。"""

from mars.graph.nodes.student import run_student
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, without_state


def test_student_writes_optimized_prompt() -> None:
    result = state_invoke(
        run_student,
        base_state(),
        ScriptedAdapter([{"optimized_prompt": "改写稿"}]),
    )
    assert result["optimized_prompt"] == "改写稿"
    assert set(result) == {"optimized_prompt", "trace"}


def test_student_llm_failure_keeps_working_prompt() -> None:
    result = state_invoke(run_student, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert result["optimized_prompt"] == "待优化提示词"
    assert any(issue["code"] == "E2-LLM-FAILED" for issue in result["trace"][0]["issues"])


def test_student_missing_questions_is_fatal() -> None:
    try:
        state_invoke(run_student, without_state("questions"), ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-QUESTIONS"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")

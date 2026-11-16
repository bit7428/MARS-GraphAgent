"""Target 节点测试。"""

from mars.graph.nodes.target import run_target
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke, target_handler
from mars.tests.fixtures.states import base_state, without_state


def test_target_pass_routes_output() -> None:
    result = state_invoke(run_target, base_state(), ScriptedAdapter([target_handler(passed=True)]))
    assert result["route_target"] == "output"
    assert set(result) == {"route_target", "trace"}


def test_target_fail_routes_manager() -> None:
    result = state_invoke(run_target, base_state(), ScriptedAdapter([target_handler(passed=False)]))
    assert result["route_target"] == "manager"


def test_target_missing_criterion_is_undecidable() -> None:
    payload = {"criteria": [], "passed": True, "reason": "缺少指标"}
    result = state_invoke(run_target, base_state(), ScriptedAdapter([payload]))
    assert result["route_target"] == "manager"
    assert any(issue["code"] == "E2-TARGET-UNDECIDABLE" for issue in result["trace"][0]["issues"])


def test_target_llm_failure_routes_manager() -> None:
    result = state_invoke(run_target, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert result["route_target"] == "manager"
    assert any(issue["code"] == "E2-TARGET-UNDECIDABLE" for issue in result["trace"][0]["issues"])


def test_target_does_not_modify_prompt_or_criteria() -> None:
    state = base_state()
    result = state_invoke(run_target, state, ScriptedAdapter([target_handler(passed=True)]))
    assert "optimized_prompt" not in result
    assert "performance_criteria" not in result


def test_target_missing_counter_is_fatal() -> None:
    try:
        state_invoke(run_target, without_state("tsc_count"), ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-TSC-COUNT"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")

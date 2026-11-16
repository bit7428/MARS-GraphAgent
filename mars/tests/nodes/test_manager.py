"""Manager 节点测试。"""

from typing import Any

from mars.graph.nodes.manager import run_manager
from mars.graph.state.constants import M_MAX
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, criterion, question, subtask, without_state


def _manager_payload(target: str) -> dict[str, Any]:
    return {
        "user_defect": target == "user",
        "planner_defect": target == "planner",
        "teacher_defect": target == "teacher",
        "reason": "测试",
    }


def test_manager_rollback_to_user_clears_loop_state() -> None:
    state = base_state(tsc_count=2)
    result = state_invoke(run_manager, state, ScriptedAdapter([_manager_payload("user")]))
    assert result["route_manager"] == "user"
    assert result["m_count"] == 1
    assert result["working_prompt"] == ""
    assert result["optimized_prompt"] == ""
    assert result["subtasks"] == []
    assert result["questions"] == []
    assert result["heuristic_score"] is None
    assert result["execution_score"] is None
    assert result["tsc_count"] == 0


def test_manager_rollback_to_planner_keeps_subtasks() -> None:
    state = base_state(tsc_count=2)
    result = state_invoke(run_manager, state, ScriptedAdapter([_manager_payload("planner")]))
    assert result["route_manager"] == "planner"
    assert result["m_count"] == 1
    # 保留意味着不写该键，而不是写成空表
    assert "subtasks" not in result
    assert result["questions"] == []
    assert result["optimized_prompt"] == ""
    assert result["tsc_count"] == 0


def test_manager_rollback_to_teacher_snapshots_prompt() -> None:
    state = base_state(tsc_count=2)
    result = state_invoke(run_manager, state, ScriptedAdapter([_manager_payload("teacher")]))
    assert result["route_manager"] == "teacher"
    assert result["m_count"] == 1
    assert result["working_prompt"] == state["optimized_prompt"]
    assert result["optimized_prompt"] == ""
    assert "tsc_count" not in result


def test_manager_m_limit_forces_output_without_increment() -> None:
    state = base_state(m_count=M_MAX)
    adapter = ScriptedAdapter([])
    result = state_invoke(run_manager, state, adapter)
    assert result["route_manager"] == "output"
    assert result["m_count"] == M_MAX
    assert "M 超限" in result["trace"][0]["summary"]
    assert adapter.calls == []


def test_manager_llm_failure_defaults_teacher() -> None:
    result = state_invoke(run_manager, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert result["route_manager"] == "teacher"
    assert result["m_count"] == 1
    codes = [issue["code"] for issue in result["trace"][0]["issues"]]
    assert "E2-LLM-FAILED" in codes
    assert "E2-MANAGER-ROUTE" in codes


def test_manager_priority_prefers_user_then_planner() -> None:
    state = base_state()
    both = {
        "user_defect": True,
        "planner_defect": True,
        "teacher_defect": True,
        "reason": "多缺陷",
    }
    result = state_invoke(run_manager, state, ScriptedAdapter([both]))
    assert result["route_manager"] == "user"

    later = {
        "user_defect": False,
        "planner_defect": True,
        "teacher_defect": True,
        "reason": "后两级缺陷",
    }
    result = state_invoke(run_manager, state, ScriptedAdapter([later]))
    assert result["route_manager"] == "planner"

    none = {
        "user_defect": False,
        "planner_defect": False,
        "teacher_defect": False,
        "reason": "无明确缺陷",
    }
    result = state_invoke(run_manager, state, ScriptedAdapter([none]))
    assert result["route_manager"] == "teacher"


def test_manager_missing_field_is_fatal() -> None:
    state = without_state("heuristic_score")
    try:
        state_invoke(run_manager, state, ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-HEURISTIC-SCORE"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")


def test_manager_cleanup_and_counter_are_single_update() -> None:
    state = base_state(
        subtasks=[subtask()],
        questions=[question()],
        performance_criteria=[criterion()],
        tsc_count=3,
    )
    result = state_invoke(run_manager, state, ScriptedAdapter([_manager_payload("teacher")]))
    assert "m_count" in result
    assert "working_prompt" in result
    assert result["trace"][0]["side_effects"]

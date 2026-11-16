"""Critic 节点测试。"""

from typing import Any

from mars.graph.nodes.critic import run_critic
from mars.graph.state.constants import TSC_MAX
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, auto_critic, state_invoke
from mars.tests.fixtures.states import base_state, question, score, subtask, without_state


def _critic_payload(*, passed: bool, value: int = 100, unknown: bool = False) -> dict[str, Any]:
    payload = auto_critic(
        "- s001｜open｜0\n- q001｜open｜0",
        passed=passed,
        value=value,
    )
    if unknown:
        payload["question_scores"].append({"id": "q999", "score": 10})
    return payload


def test_critic_pass_routes_to_target_without_count_increment() -> None:
    result = state_invoke(run_critic, base_state(), ScriptedAdapter([_critic_payload(passed=True)]))
    assert result["route_critic"] == "target"
    assert result["tsc_count"] == 0
    assert result["subtasks"][0]["status"] == "dropped"
    assert result["questions"][0]["status"] == "dropped"


def test_critic_fail_snapshots_prompt_and_increments_tsc() -> None:
    state = base_state()
    result = state_invoke(
        run_critic, state, ScriptedAdapter([_critic_payload(passed=False, value=10)])
    )
    assert result["route_critic"] == "teacher"
    assert result["working_prompt"] == state["optimized_prompt"]
    assert result["optimized_prompt"] == ""
    assert result["tsc_count"] == 1
    assert result["subtasks"][0]["status"] == "pending"


def test_critic_tsc_limit_goes_target() -> None:
    state = base_state(tsc_count=TSC_MAX)
    result = state_invoke(
        run_critic, state, ScriptedAdapter([_critic_payload(passed=False, value=10)])
    )
    assert result["route_critic"] == "target"
    assert result["tsc_count"] == TSC_MAX
    assert "TSC 超限" in result["trace"][0]["summary"]


def test_critic_keeps_dropped_items() -> None:
    state = base_state(
        subtasks=[subtask("s001", status="dropped", value=90)],
        questions=[question("q001", status="dropped", value=80)],
    )
    result = state_invoke(run_critic, state, ScriptedAdapter([_critic_payload(passed=True)]))
    assert result["subtasks"][0]["status"] == "dropped"
    assert result["questions"][0]["status"] == "dropped"


def test_critic_unknown_ids_are_level_two_issue() -> None:
    result = state_invoke(
        run_critic,
        base_state(),
        ScriptedAdapter([_critic_payload(passed=True, unknown=True)]),
    )
    assert any(issue["code"] == "E2-LLM-SCHEMA" for issue in result["trace"][0]["issues"])


def test_critic_llm_failure_falls_back_and_continues_loop() -> None:
    result = state_invoke(run_critic, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert result["route_critic"] == "teacher"
    assert result["tsc_count"] == 1
    assert any(issue["code"] == "E2-LLM-FAILED" for issue in result["trace"][0]["issues"])


def test_critic_clears_questions_but_keeps_history() -> None:
    state = base_state(
        questions=[question("q001", status="open"), question("q002", status="dropped")]
    )
    adapter = ScriptedAdapter(
        [
            {
                "subtask_scores": [{"id": "s001", "score": 100}],
                "question_scores": [{"id": "q001", "score": 90}, {"id": "q002", "score": 90}],
                "heuristic": {
                    "score": 90,
                    "dimensions": {},
                    "summary": "清晰",
                    "evidence": ["q001"],
                },
                "execution": {
                    "score": 90,
                    "dimensions": {},
                    "summary": "有效",
                    "evidence": [],
                },
                "passed": True,
            }
        ]
    )
    result = state_invoke(run_critic, state, adapter)
    assert len(result["questions"]) == 2
    assert all(item["status"] == "dropped" for item in result["questions"])


def test_critic_missing_required_is_fatal() -> None:
    try:
        state_invoke(run_critic, without_state("questions"), ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-QUESTIONS"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")


def test_critic_reads_existing_scores_when_llm_fails() -> None:
    existing = score(55, dimensions={"depth": 40})
    state = base_state(heuristic_score=existing)
    result = state_invoke(run_critic, state, ScriptedAdapter([LLMError("boom")]))
    assert result["heuristic_score"] == existing

"""Planner 节点测试。"""

from mars.graph.nodes.planner import run_planner
from mars.graph.state.errors import FatalStateError, LLMError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, without_state


def test_planner_updates_working_prompt_and_appends_subtasks() -> None:
    adapter = ScriptedAdapter([{"working_prompt": "第一版", "subtasks": [{"content": "新子任务"}]}])
    result = state_invoke(run_planner, base_state(), adapter)
    assert result["working_prompt"] == "第一版"
    assert [item["id"] for item in result["subtasks"]] == ["s001", "s002"]
    assert result["subtasks"][1]["source"] == "planner"
    assert result["subtasks"][1]["status"] == "pending"


def test_planner_llm_failure_falls_back_to_initial_prompt() -> None:
    result = state_invoke(run_planner, base_state(), ScriptedAdapter([LLMError("boom")]))
    assert result["working_prompt"] == "初始提示词"
    assert [item["id"] for item in result["subtasks"]] == ["s001"]
    assert any(issue["code"] == "E2-LLM-FAILED" for issue in result["trace"][0]["issues"])


def test_planner_missing_initial_prompt_is_fatal() -> None:
    try:
        state_invoke(run_planner, without_state("initial_prompt"), ScriptedAdapter([]))
    except FatalStateError as exc:
        assert exc.issues[0].code == "E1-MISSING-INITIAL-PROMPT"
    else:  # pragma: no cover
        raise AssertionError("应抛出 FatalStateError")

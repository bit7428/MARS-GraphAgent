"""User 节点测试。"""

import pytest

from mars.graph.nodes.user import run_user
from mars.graph.state.errors import FatalStateError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, without_state


def test_user_keeps_initial_input() -> None:
    result = state_invoke(run_user, base_state(), ScriptedAdapter([]))
    assert result["initial_prompt"] == "初始提示词"
    assert result["optimization_goal"] == "让提示词更清晰"
    assert len(result["trace"]) == 1


def test_user_appends_supplement() -> None:
    supplement = {"initial_prompt": "补充内容", "mode": "append"}
    result = state_invoke(
        run_user,
        base_state(),
        ScriptedAdapter([]),
        user_supplement=supplement,
    )
    assert result["initial_prompt"] == "初始提示词\n\n补充内容"
    assert result["optimization_goal"] == "让提示词更清晰"


def test_user_replaces_supplement() -> None:
    supplement = {
        "initial_prompt": "新提示词",
        "optimization_goal": "新目标",
        "mode": "replace",
    }
    result = state_invoke(
        run_user,
        base_state(),
        ScriptedAdapter([]),
        user_supplement=supplement,
    )
    assert result["initial_prompt"] == "新提示词"
    assert result["optimization_goal"] == "新目标"


def test_user_missing_input_is_level_two() -> None:
    state = without_state("initial_prompt", "optimization_goal")
    result = state_invoke(run_user, state, ScriptedAdapter([]))
    issues = result["trace"][0]["issues"]
    assert any(issue["level"] == 2 for issue in issues)
    assert result["initial_prompt"] == ""


def test_user_is_not_llm_node() -> None:
    adapter = ScriptedAdapter([])
    state_invoke(run_user, base_state(), adapter)
    assert adapter.calls == []


def test_user_does_not_raise_on_missing() -> None:
    # 文档：首次初始化无报错，缺输入只记 2 级
    state = without_state("initial_prompt")
    result = state_invoke(run_user, state, ScriptedAdapter([]))
    assert "trace" in result
    with pytest.raises(FatalStateError):
        # 对照：其他节点的必填缺失仍是 1 级
        from mars.graph.nodes.student import run_student

        state_invoke(run_student, without_state("working_prompt"), ScriptedAdapter([]))

"""不变量测试。"""

import json
from typing import cast

from langgraph.checkpoint.memory import InMemorySaver

from mars.graph.builder import build_graph
from mars.graph.nodes.critic import run_critic
from mars.graph.nodes.teacher import run_teacher
from mars.graph.state.constants import TSC_MAX
from mars.graph.state.schema import GraphState
from mars.runtime.breakpoints import make_gate
from mars.tests.fixtures.fakes import (
    LabeledAdapter,
    ScriptedAdapter,
    auto_critic,
    default_handlers,
    make_config,
    state_invoke,
)
from mars.tests.fixtures.states import base_state, initial_state


def _run_happy() -> GraphState:
    app = build_graph(gate_factory=make_gate, checkpointer=InMemorySaver())
    config = make_config(LabeledAdapter(default_handlers()))
    return cast(GraphState, app.invoke(initial_state(), config))


def test_performance_criteria_is_immutable() -> None:
    result = _run_happy()
    assert result["performance_criteria"] == initial_state()["performance_criteria"]


def test_state_json_roundtrip() -> None:
    result = _run_happy()
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


def test_critic_teacher_snapshot_invariant() -> None:
    state = base_state()
    result = state_invoke(
        run_critic,
        state,
        ScriptedAdapter([auto_critic("- s001｜open｜0\n- q001｜open｜0", passed=False, value=10)]),
    )
    assert result["working_prompt"] == state["optimized_prompt"]
    assert result["optimized_prompt"] == ""


def test_tsc_count_only_increments_on_rollback() -> None:
    pass_result = state_invoke(
        run_critic,
        base_state(),
        ScriptedAdapter([auto_critic("- s001｜x｜0\n- q001｜x｜0", passed=True)]),
    )
    assert pass_result["tsc_count"] == 0
    fail_result = state_invoke(
        run_critic,
        base_state(tsc_count=1),
        ScriptedAdapter([auto_critic("- s001｜x｜0\n- q001｜x｜0", passed=False, value=10)]),
    )
    assert fail_result["tsc_count"] == 2


def test_tsc_count_does_not_exceed_limit_on_target_branch() -> None:
    result = state_invoke(
        run_critic,
        base_state(tsc_count=TSC_MAX),
        ScriptedAdapter([auto_critic("- s001｜x｜0\n- q001｜x｜0", passed=False, value=10)]),
    )
    assert result["tsc_count"] == TSC_MAX
    assert result["route_critic"] == "target"


def test_subtasks_and_questions_are_append_only() -> None:
    state = base_state()
    teacher_result = state_invoke(
        run_teacher,
        state,
        ScriptedAdapter([{"questions": [{"content": "追问"}]}]),
    )
    assert len(teacher_result["questions"]) == len(state["questions"]) + 1
    assert teacher_result["questions"][0] == state["questions"][0]


def test_structured_retry_is_idempotent_for_lists() -> None:
    adapter = ScriptedAdapter(["不是 JSON", {"questions": [{"content": "重试后提问"}]}])
    result = state_invoke(run_teacher, base_state(), adapter)
    assert len(result["questions"]) == 2
    assert len(adapter.calls) == 2


def test_trace_is_append_only_across_nodes() -> None:
    result = _run_happy()
    nodes = [trace["node"] for trace in result["trace"]]
    assert len(nodes) == len(set(nodes))


def test_no_node_writes_performance_criteria() -> None:
    result = _run_happy()
    for trace in result["trace"]:
        assert "performance_criteria" not in trace["writes"]

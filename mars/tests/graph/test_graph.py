"""全图集成测试。"""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from mars.graph.builder import build_graph
from mars.graph.state.constants import M_MAX, TSC_MAX
from mars.graph.state.schema import GraphState
from mars.runtime.breakpoints import build_resume_command, make_gate
from mars.tests.fixtures.fakes import (
    HandlerSpec,
    LabeledAdapter,
    auto_critic,
    default_handlers,
    make_config,
    manager_handler,
    planner_handler,
    student_handler,
    target_handler,
    teacher_handler,
)
from mars.tests.fixtures.states import initial_state


def _graph() -> Any:
    return build_graph(gate_factory=make_gate, checkpointer=InMemorySaver())


def _run(adapter: LabeledAdapter, **config: Any) -> tuple[Any, Any, GraphState]:
    app = _graph()
    run_config = make_config(adapter, **config)
    result = app.invoke(initial_state(), run_config)
    return app, run_config, result


def _node_sequence(state: GraphState) -> list[str]:
    return [
        trace["node"]
        for trace in state.get("trace", [])
        if not str(trace["node"]).startswith("gate:")
    ]


def _issues(state: GraphState) -> list[Any]:
    return [issue for trace in state.get("trace", []) for issue in trace.get("issues", [])]


def test_happy_path_reaches_output() -> None:
    adapter = LabeledAdapter(default_handlers())
    _, _, result = _run(adapter)
    assert _node_sequence(result) == [
        "user",
        "planner",
        "teacher",
        "student",
        "critic",
        "target",
        "output",
    ]
    assert result["optimized_prompt"] == "学生优化后的提示词"
    assert result["route_target"] == "output"
    assert result["report_md"]
    assert result["performance_criteria"]
    assert _issues(result) == []


def test_tsc_limit_routes_to_target() -> None:
    handlers = default_handlers(critic_passed=False)
    handlers["critic"] = lambda body: auto_critic(body, passed=False, value=10)
    adapter = LabeledAdapter(handlers)
    _, _, result = _run(adapter)
    assert result["tsc_count"] == TSC_MAX
    assert result["route_target"] == "output"
    # 初始一轮 + TSC_MAX 轮回边，共 TSC_MAX+1 次 Teacher/Critic
    assert adapter.calls.count("teacher") == TSC_MAX + 1
    assert adapter.calls.count("critic") == TSC_MAX + 1
    assert _issues(result) == []


def test_m_limit_forces_failure_report() -> None:
    handlers = default_handlers(target_passed=False)
    handlers["target"] = target_handler(passed=False)
    adapter = LabeledAdapter(handlers)
    _, _, result = _run(adapter)
    assert result["m_count"] == M_MAX
    assert result["route_manager"] == "output"
    report = result.get("report_md") or ""
    assert "M 超限/未通过验收" in report
    assert adapter.calls.count("manager") == M_MAX
    assert _issues(result) == []


@pytest.mark.parametrize("manager_target", ["user", "planner"])
def test_manager_rollback_to_user_or_planner(manager_target: str) -> None:
    handlers: dict[str, HandlerSpec] = {
        "planner": planner_handler,
        "teacher": teacher_handler,
        "student": student_handler,
        "critic": lambda body: auto_critic(body, passed=True),
        "target": [target_handler(passed=False), target_handler(passed=True)],
        "manager": manager_handler(manager_target),
    }
    adapter = LabeledAdapter(handlers)
    _, _, result = _run(adapter)
    assert result["m_count"] == 1
    assert result["route_target"] == "output"
    assert result["optimized_prompt"] == "学生优化后的提示词"
    assert adapter.calls.count("manager") == 1
    assert adapter.calls.count("planner") == 2
    assert _issues(result) == []


def test_manager_rollback_to_teacher_keeps_tsc() -> None:
    handlers: dict[str, HandlerSpec] = {
        "planner": planner_handler,
        "teacher": teacher_handler,
        "student": student_handler,
        "critic": [
            lambda body: auto_critic(body, passed=False, value=10),
            lambda body: auto_critic(body, passed=True),
        ],
        "target": [target_handler(passed=False), target_handler(passed=True)],
        "manager": manager_handler("teacher"),
    }
    adapter = LabeledAdapter(handlers)
    _, _, result = _run(adapter)
    assert result["m_count"] == 1
    assert result["tsc_count"] == 1
    assert result["route_target"] == "output"
    assert result["optimized_prompt"]
    assert adapter.calls.count("manager") == 1


def test_breakpoint_continue() -> None:
    adapter = LabeledAdapter(default_handlers())
    app, config, first = _run(adapter, breakpoints={"user->planner"})
    assert "working_prompt" not in first
    snapshot = app.get_state(config)
    assert snapshot.next == ("gate__user__planner",)
    interrupt = snapshot.tasks[0].interrupts[0].value
    assert interrupt["edge_id"] == "user->planner"
    assert interrupt["counters"] == {"tsc_count": 0, "m_count": 0}
    assert "initial_prompt" not in interrupt
    resumed = app.invoke(build_resume_command("continue"), config)
    assert resumed["optimized_prompt"] == "学生优化后的提示词"
    gate_traces = [t for t in resumed["trace"] if str(t["node"]).startswith("gate:")]
    assert gate_traces[0]["human_intervention"] is True


def test_breakpoint_reroute_to_output() -> None:
    handlers = default_handlers(target_passed=False)
    handlers["target"] = target_handler(passed=False)
    adapter = LabeledAdapter(handlers)
    app, config, _ = _run(adapter, breakpoints={"target->manager"})
    snapshot = app.get_state(config)
    assert snapshot.next == ("gate__target__manager",)
    result = app.invoke(
        build_resume_command({"action": "reroute", "target": "output", "operator": "tester"}),
        config,
    )
    assert result["m_count"] == 0
    assert result["report_md"]
    assert "route_manager" not in result
    gate = next(t for t in result["trace"] if str(t["node"]).startswith("gate:"))
    assert gate["new_route"] == "output"
    assert gate["operator"] == "tester"


def test_breakpoint_reroute_rejected_by_contract() -> None:
    adapter = LabeledAdapter(default_handlers())
    app, config, _ = _run(adapter, breakpoints={"user->planner"})
    result = app.invoke(
        build_resume_command({"action": "reroute", "target": "target"}),
        config,
    )
    # 改道被拒绝后仍按原路由执行 Planner
    assert result["optimized_prompt"] == "学生优化后的提示词"
    gate = next(t for t in result["trace"] if str(t["node"]).startswith("gate:"))
    assert any(issue["code"] == "E2-REROUTE-REJECTED" for issue in gate["issues"])
    assert gate["new_route"] == "planner"


def test_breakpoint_abort() -> None:
    adapter = LabeledAdapter(default_handlers())
    app, config, _ = _run(adapter, breakpoints={"user->planner"})
    result = app.invoke(build_resume_command("abort"), config)
    assert "working_prompt" not in result
    gate = next(t for t in result["trace"] if str(t["node"]).startswith("gate:"))
    assert gate["new_route"] is None
    assert "中止" in gate["summary"]


def test_invalid_resume_payload_keeps_original_route() -> None:
    adapter = LabeledAdapter(default_handlers())
    app, config, _ = _run(adapter, breakpoints={"user->planner"})
    result = app.invoke(build_resume_command({"action": "unknown"}), config)
    assert result["optimized_prompt"] == "学生优化后的提示词"
    gate = next(t for t in result["trace"] if str(t["node"]).startswith("gate:"))
    assert any(issue["code"] == "E2-BREAKPOINT-PAYLOAD" for issue in gate["issues"])

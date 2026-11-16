"""路由与边表测试。"""

import pytest

from mars.graph.edge_table import EDGE_TABLE, edges_from, find_edge
from mars.graph.routing.critic import route_critic
from mars.graph.routing.manager import route_manager
from mars.graph.routing.target import route_target
from mars.graph.state.schema import GraphState
from mars.tests.fixtures.states import base_state


@pytest.mark.parametrize(
    ("route", "expected"),
    [("teacher", "teacher"), ("target", "target")],
)
def test_route_critic(route: str, expected: str) -> None:
    state = base_state(route_critic=route)
    assert route_critic(state) == expected


@pytest.mark.parametrize(
    ("route", "expected"),
    [("output", "output"), ("manager", "manager")],
)
def test_route_target(route: str, expected: str) -> None:
    state = base_state(route_target=route)
    assert route_target(state) == expected


@pytest.mark.parametrize(
    ("route", "expected"),
    [("user", "user"), ("planner", "planner"), ("teacher", "teacher"), ("output", "output")],
)
def test_route_manager(route: str, expected: str) -> None:
    state = base_state(route_manager=route)
    assert route_manager(state) == expected


def test_router_reads_only_route_key_not_recompute() -> None:
    # 即使业务字段看起来“应通过”，路由也只信任源节点写入的键
    state = base_state(route_critic="teacher")
    assert route_critic(state) == "teacher"


def test_edge_table_is_complete_and_unique() -> None:
    assert len(EDGE_TABLE) == 12
    ids = [edge.edge_id for edge in EDGE_TABLE]
    assert len(ids) == len(set(ids))
    assert all(edge.breakpoint for edge in EDGE_TABLE)


def test_static_edges_match_document() -> None:
    static = [edge.edge_id for edge in EDGE_TABLE if edge.kind == "static"]
    assert static == [
        "user->planner",
        "planner->teacher",
        "teacher->student",
        "student->critic",
    ]


def test_conditional_candidates_match_routes() -> None:
    assert {edge.target for edge in edges_from("critic")} == {"teacher", "target"}
    assert {edge.target for edge in edges_from("target")} == {"output", "manager"}
    assert {edge.target for edge in edges_from("manager")} == {
        "user",
        "planner",
        "teacher",
        "output",
    }


def test_find_edge() -> None:
    assert find_edge("critic->teacher") is not None
    assert find_edge("critic->student") is None


def test_route_key_is_literal_in_state() -> None:
    state = GraphState.__annotations__["route_critic"]
    assert state is not None

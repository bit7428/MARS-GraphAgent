"""图装配：只做 add_node / add_edge，不写业务逻辑。"""

from collections.abc import Callable, Hashable
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mars.graph.edge_table import EDGE_TABLE, EdgeSpec
from mars.graph.nodes.critic import run_critic
from mars.graph.nodes.manager import run_manager
from mars.graph.nodes.output import run_output
from mars.graph.nodes.planner import run_planner
from mars.graph.nodes.student import run_student
from mars.graph.nodes.target import run_target
from mars.graph.nodes.teacher import run_teacher
from mars.graph.nodes.user import run_user
from mars.graph.routing.critic import route_critic
from mars.graph.routing.manager import route_manager
from mars.graph.routing.target import route_target
from mars.graph.state.schema import GraphState

GateFactory = Callable[[EdgeSpec], Callable[..., Any]]

_NODE_FUNCTIONS: dict[str, Any] = {
    "user": run_user,
    "planner": run_planner,
    "teacher": run_teacher,
    "student": run_student,
    "critic": run_critic,
    "target": run_target,
    "output": run_output,
    "manager": run_manager,
}

_ROUTERS: dict[str, Callable[[GraphState], str]] = {
    "critic": cast(Callable[[GraphState], str], route_critic),
    "target": cast(Callable[[GraphState], str], route_target),
    "manager": cast(Callable[[GraphState], str], route_manager),
}


def gate_node_name(edge: EdgeSpec) -> str:
    """gate 节点名与 edge_id 一一对应，便于事件回溯。"""
    return f"gate__{edge.source}__{edge.target}"


def build_graph(
    *,
    gate_factory: GateFactory,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[GraphState, Any, GraphState, GraphState]:
    """按边表装配全图；断点 gate 由 runtime 注入。"""
    workflow = StateGraph(GraphState)
    for name, fn in _NODE_FUNCTIONS.items():
        workflow.add_node(name, fn)
    for edge in EDGE_TABLE:
        workflow.add_node(gate_node_name(edge), gate_factory(edge))

    conditional_sources: dict[str, list[EdgeSpec]] = {}
    for edge in EDGE_TABLE:
        if edge.kind == "static":
            workflow.add_edge(edge.source, gate_node_name(edge))
        else:
            conditional_sources.setdefault(edge.source, []).append(edge)

    for source, edges in conditional_sources.items():
        path_map: dict[Hashable, str] = {edge.target: gate_node_name(edge) for edge in edges}
        workflow.add_conditional_edges(source, _ROUTERS[source], path_map)

    workflow.add_edge(START, "user")
    workflow.add_edge("output", END)
    return workflow.compile(checkpointer=checkpointer)

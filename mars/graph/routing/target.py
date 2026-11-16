"""Target 条件边路由（纯函数）。"""

from typing import Literal

from mars.graph.state.schema import GraphState


def route_target(state: GraphState) -> Literal["output", "manager"]:
    """读取 Target 写入的路由键。"""
    return state["route_target"]

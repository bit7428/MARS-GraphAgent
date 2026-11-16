"""Manager 条件边路由（纯函数）。"""

from typing import Literal

from mars.graph.state.schema import GraphState


def route_manager(state: GraphState) -> Literal["user", "planner", "teacher", "output"]:
    """读取 Manager 写入的唯一回退路由。"""
    return state["route_manager"]

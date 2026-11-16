"""Critic 条件边路由（纯函数，只做映射）。"""

from typing import Literal

from mars.graph.state.schema import GraphState


def route_critic(state: GraphState) -> Literal["teacher", "target"]:
    """读取源节点写入的路由键，不重新计算业务条件。"""
    return state["route_critic"]

"""GraphState 定义。字段与文档 1–11 一一对应，禁止增加未登记键。"""

from typing import Annotated, Literal, TypedDict

from mars.graph.state.models import (
    NodeTrace,
    PerformanceCriterion,
    Question,
    ScoreDetail,
    Subtask,
)
from mars.graph.state.reducers import append_trace


class GraphState(TypedDict, total=False):
    """全局状态；total=False 让「缺失」与 None 保留业务语义。"""

    # 1–11 业务字段
    initial_prompt: str
    working_prompt: str
    optimized_prompt: str
    optimization_goal: str
    subtasks: list[Subtask]
    questions: list[Question]
    heuristic_score: ScoreDetail | None
    execution_score: ScoreDetail | None
    performance_criteria: list[PerformanceCriterion]
    tsc_count: int
    m_count: int

    # 非业务通道：路由键仅供条件边读取
    route_critic: Literal["teacher", "target"]
    route_target: Literal["output", "manager"]
    route_manager: Literal["user", "planner", "teacher", "output"]

    # 追踪与产物
    trace: Annotated[list[NodeTrace], append_trace]
    report_md: str | None

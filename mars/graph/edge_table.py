"""边表常量，与 MARS-Prompt.md 边表逐条对应。"""

from typing import Literal, NamedTuple


class EdgeSpec(NamedTuple):
    """一条逻辑边的完整声明。"""

    edge_id: str
    source: str
    target: str
    kind: Literal["static", "conditional"]
    condition: str
    side_effect: tuple[str, ...]
    breakpoint: bool


EDGE_TABLE: tuple[EdgeSpec, ...] = (
    EdgeSpec("user->planner", "user", "planner", "static", "无条件", (), True),
    EdgeSpec("planner->teacher", "planner", "teacher", "static", "无条件", (), True),
    EdgeSpec("teacher->student", "teacher", "student", "static", "无条件", (), True),
    EdgeSpec("student->critic", "student", "critic", "static", "无条件", (), True),
    EdgeSpec(
        "critic->teacher",
        "critic",
        "teacher",
        "conditional",
        "不满足要求且 10<TSC_max",
        ("2←3", "3 置空", "10+1"),
        True,
    ),
    EdgeSpec(
        "critic->target",
        "critic",
        "target",
        "conditional",
        "满足要求或 10≥TSC_max",
        (),
        True,
    ),
    EdgeSpec("target->output", "target", "output", "conditional", "验收通过", (), True),
    EdgeSpec("target->manager", "target", "manager", "conditional", "验收不通过", (), True),
    EdgeSpec(
        "manager->user",
        "manager",
        "user",
        "conditional",
        "按 B6 规则（User 优先）",
        ("11+1", "回 User 清理"),
        True,
    ),
    EdgeSpec(
        "manager->planner",
        "manager",
        "planner",
        "conditional",
        "按 B6 规则（Planner 次优先）",
        ("11+1", "回 Planner 清理"),
        True,
    ),
    EdgeSpec(
        "manager->teacher",
        "manager",
        "teacher",
        "conditional",
        "按 B6 规则（Teacher 兜底）",
        ("11+1", "回 Teacher 清理"),
        True,
    ),
    EdgeSpec(
        "manager->output",
        "manager",
        "output",
        "conditional",
        "11≥M_max",
        ("失败标记",),
        True,
    ),
)


def edges_from(source: str) -> tuple[EdgeSpec, ...]:
    """返回某源节点的全部逻辑边。"""
    return tuple(edge for edge in EDGE_TABLE if edge.source == source)


def find_edge(edge_id: str) -> EdgeSpec | None:
    """按 edge_id 查找边。"""
    return next((edge for edge in EDGE_TABLE if edge.edge_id == edge_id), None)

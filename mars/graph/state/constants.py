"""状态键常量与循环阈值。

编号 1–11 与代码名的映射只集中在这里，业务代码禁止出现编号魔法字符串。
"""

from typing import Final

# 文档 10/11 的循环上限
TSC_MAX: Final[int] = 5
M_MAX: Final[int] = 3
# 文档：>85 划去子任务；>60 划去提问；<60 时优先聚焦低分维度
SUBTASK_DONE_THRESHOLD: Final[int] = 85
QUESTION_RESOLVED_THRESHOLD: Final[int] = 60
LOW_SCORE_THRESHOLD: Final[int] = 60

# 文档编号 → 代码名
FIELD_INDEX: Final[dict[str, int]] = {
    "initial_prompt": 1,
    "working_prompt": 2,
    "optimized_prompt": 3,
    "optimization_goal": 4,
    "subtasks": 5,
    "questions": 6,
    "heuristic_score": 7,
    "execution_score": 8,
    "performance_criteria": 9,
    "tsc_count": 10,
    "m_count": 11,
}

# 文档要求的业务字段顺序
BUSINESS_FIELDS: Final[tuple[str, ...]] = tuple(FIELD_INDEX)

NODE_NAMES: Final[tuple[str, ...]] = (
    "user",
    "planner",
    "teacher",
    "student",
    "critic",
    "target",
    "output",
    "manager",
)

# 文档中的 6 个 LLM 节点（User/Output 为普通节点）
LLM_NODES: Final[tuple[str, ...]] = (
    "planner",
    "teacher",
    "student",
    "critic",
    "target",
    "manager",
)

# 仅条件边源节点持有路由键
ROUTE_KEYS: Final[dict[str, str]] = {
    "critic": "route_critic",
    "target": "route_target",
    "manager": "route_manager",
}

ROUTE_VALUES: Final[dict[str, frozenset[str]]] = {
    "route_critic": frozenset({"teacher", "target"}),
    "route_target": frozenset({"output", "manager"}),
    "route_manager": frozenset({"user", "planner", "teacher", "output"}),
}

# 断点改道允许的全局候选（文档 R7.7）
REROUTE_GLOBAL_TARGETS: Final[frozenset[str]] = frozenset(
    {"user", "planner", "teacher", "manager", "target"}
)

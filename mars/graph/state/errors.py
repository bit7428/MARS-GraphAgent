"""错误类型、报错码与分级。"""

from dataclasses import dataclass
from typing import Literal

from mars.graph.state.models import IssueDict

# 必填字段缺失（1 级）
E1_MISSING: dict[str, str] = {
    "initial_prompt": "E1-MISSING-INITIAL-PROMPT",
    "working_prompt": "E1-MISSING-WORKING-PROMPT",
    "optimized_prompt": "E1-MISSING-OPTIMIZED-PROMPT",
    "optimization_goal": "E1-MISSING-OPTIMIZATION-GOAL",
    "subtasks": "E1-MISSING-SUBTASKS",
    "questions": "E1-MISSING-QUESTIONS",
    "heuristic_score": "E1-MISSING-HEURISTIC-SCORE",
    "execution_score": "E1-MISSING-EXECUTION-SCORE",
    "performance_criteria": "E1-MISSING-PERFORMANCE-CRITERIA",
    "tsc_count": "E1-MISSING-TSC-COUNT",
    "m_count": "E1-MISSING-M-COUNT",
}

# 待选字段缺失（2 级）
E2_MISSING: dict[str, str] = {
    field: code.replace("E1-", "E2-") for field, code in E1_MISSING.items()
}

E2_SCHEMA: dict[str, str] = {
    "initial_prompt": "E2-SCHEMA-INITIAL-PROMPT",
    "working_prompt": "E2-SCHEMA-WORKING-PROMPT",
    "optimized_prompt": "E2-SCHEMA-OPTIMIZED-PROMPT",
    "optimization_goal": "E2-SCHEMA-OPTIMIZATION-GOAL",
    "subtasks": "E2-SCHEMA-SUBTASK",
    "questions": "E2-SCHEMA-QUESTION",
    "heuristic_score": "E2-SCHEMA-HEURISTIC-SCORE",
    "execution_score": "E2-SCHEMA-EXECUTION-SCORE",
    "performance_criteria": "E2-SCHEMA-PERFORMANCE-CRITERIA",
    "tsc_count": "E2-SCHEMA-TSC-COUNT",
    "m_count": "E2-SCHEMA-M-COUNT",
}

E2_CONDITIONAL_MISSING: dict[str, str] = {
    "initial_prompt": "E2-CONDITIONAL-MISSING-INITIAL-PROMPT",
    "optimization_goal": "E2-CONDITIONAL-MISSING-OPTIMIZATION-GOAL",
    "optimized_prompt": "E2-CONDITIONAL-MISSING-OPTIMIZED-PROMPT",
    "subtasks": "E2-CONDITIONAL-MISSING-SUBTASK",
    "questions": "E2-CONDITIONAL-MISSING-QUESTION",
    "heuristic_score": "E2-CONDITIONAL-MISSING-HEURISTIC-SCORE",
    "execution_score": "E2-CONDITIONAL-MISSING-EXECUTION-SCORE",
}

E2_SCHEMA_ROUTE: str = "E2-SCHEMA-ROUTE"
E2_TARGET_UNDECIDABLE: str = "E2-TARGET-UNDECIDABLE"
E2_LLM_FAILED: str = "E2-LLM-FAILED"
E2_LLM_SCHEMA: str = "E2-LLM-SCHEMA"
E2_BREAKPOINT_PAYLOAD: str = "E2-BREAKPOINT-PAYLOAD"
E2_REROUTE_REJECTED: str = "E2-REROUTE-REJECTED"
E2_MANAGER_ROUTE: str = "E2-MANAGER-ROUTE"
E2_UNKNOWN_FIELD: str = "E2-UNKNOWN-STATE-FIELD"


@dataclass(frozen=True)
class StateIssue:
    """校验问题；1 级终止，2 级继续。"""

    code: str
    level: Literal[1, 2]
    field: str | None
    message: str

    def to_dict(self) -> IssueDict:
        """转换为可写入 trace 的字典。"""
        return {
            "code": self.code,
            "level": self.level,
            "field": self.field,
            "message": self.message,
        }


class MarsError(Exception):
    """项目异常基类。"""


class FatalStateError(MarsError):
    """1 级错误：必填状态缺失或为 null，终止优化且不写入状态。"""

    def __init__(self, node: str, issues: list[StateIssue] | tuple[StateIssue, ...]) -> None:
        self.node = node
        self.issues = list(issues)
        codes = ", ".join(issue.code for issue in self.issues)
        super().__init__(f"{node}: {codes}")


class CodingContractError(MarsError):
    """节点违反读写契约或原地修改状态。"""


class LLMError(MarsError):
    """LLM 适配器调用失败。"""


class StructuredOutputError(LLMError):
    """结构化输出在有限重试后仍不合法。"""


class RunNotFoundError(MarsError):
    """运行不存在。"""

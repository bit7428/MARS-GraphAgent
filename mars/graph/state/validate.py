"""状态校验唯一入口：存在性 → 类型 → 取值范围 → 跨字段一致性。"""

from collections.abc import Mapping
from typing import Any, cast

from mars import messages
from mars.graph.state.constants import (
    BUSINESS_FIELDS,
    ROUTE_KEYS,
    ROUTE_VALUES,
)
from mars.graph.state.errors import (
    E1_MISSING,
    E2_CONDITIONAL_MISSING,
    E2_MISSING,
    E2_SCHEMA,
    E2_SCHEMA_ROUTE,
    E2_UNKNOWN_FIELD,
    StateIssue,
)
from mars.graph.state.schema import GraphState

_NON_BIZ_FIELDS = frozenset({"trace", "report_md", *ROUTE_KEYS.values()})
_KNOWN_FIELDS = frozenset(BUSINESS_FIELDS) | _NON_BIZ_FIELDS
_SUBTASK_STATUS = frozenset({"pending", "done", "dropped"})
_QUESTION_STATUS = frozenset({"open", "resolved", "dropped"})
_SUBTASK_SOURCE = frozenset({"planner", "critic", "user"})
_COMPARATORS = frozenset({"gte", "lte", "eq"})


def _issue(code: str, level: int, field: str | None, message: str) -> StateIssue:
    return StateIssue(code=code, level=1 if level == 1 else 2, field=field, message=message)


def _present(state: Mapping[str, Any], field: str) -> bool:
    return field in state and state[field] is not None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _valid_prompt(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_subtasks(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return False
        element = cast(dict[str, Any], item)
        if not isinstance(element.get("id"), str) or not element["id"].strip():
            return False
        if element["id"] in seen:
            return False
        seen.add(element["id"])
        if not isinstance(element.get("content"), str) or not element["content"].strip():
            return False
        if element.get("status") not in _SUBTASK_STATUS:
            return False
        if not _is_int(element.get("score")) or not 0 <= element["score"] <= 100:
            return False
        if "source" in element and element["source"] not in _SUBTASK_SOURCE:
            return False
    return True


def _valid_questions(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return False
        element = cast(dict[str, Any], item)
        if not isinstance(element.get("id"), str) or not element["id"].strip():
            return False
        if element["id"] in seen:
            return False
        seen.add(element["id"])
        if not isinstance(element.get("content"), str) or not element["content"].strip():
            return False
        if element.get("status") not in _QUESTION_STATUS:
            return False
        if not _is_int(element.get("score")) or not 0 <= element["score"] <= 100:
            return False
        target = element.get("target_task_id")
        if target is not None and not isinstance(target, str):
            return False
    return True


def _valid_score_detail(value: Any, *, require_evidence: bool) -> bool:
    if not isinstance(value, dict):
        return False
    detail = cast(dict[str, Any], value)
    if not _is_int(detail.get("score")) or not 0 <= detail["score"] <= 100:
        return False
    summary = detail.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    dimensions = detail.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, dict):
            return False
        if any(not isinstance(k, str) or not _is_int(v) for k, v in dimensions.items()):
            return False
    if "evidence" in detail or require_evidence:
        evidence = detail.get("evidence")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            return False
        if require_evidence and not evidence:
            return False
    return True


def _valid_criteria(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        element = cast(dict[str, Any], item)
        if not isinstance(element.get("name"), str) or not element["name"].strip():
            return False
        if not _is_number(element.get("threshold")):
            return False
        if element.get("comparator") not in _COMPARATORS:
            return False
    return True


def _valid_route(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _format_issue(field: str, value: Any) -> StateIssue | None:
    if field in {"initial_prompt", "working_prompt", "optimized_prompt", "optimization_goal"}:
        return (
            None
            if _valid_prompt(value)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_PROMPT)
        )
    if field == "subtasks":
        return (
            None
            if _valid_subtasks(value)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_SUBTASK)
        )
    if field == "questions":
        return (
            None
            if _valid_questions(value)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_QUESTION)
        )
    if field == "heuristic_score":
        return (
            None
            if _valid_score_detail(value, require_evidence=True)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_HEURISTIC)
        )
    if field == "execution_score":
        return (
            None
            if _valid_score_detail(value, require_evidence=False)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_EXECUTION)
        )
    if field == "performance_criteria":
        return (
            None
            if _valid_criteria(value)
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_CRITERIA)
        )
    if field in {"tsc_count", "m_count"}:
        return (
            None
            if _is_int(value) and value >= 0
            else _issue(E2_SCHEMA[field], 2, field, messages.SCHEMA_COUNTER)
        )
    return None  # pragma: no cover - 仅业务字段会进入本函数


def validate_state(
    state: GraphState,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> list[StateIssue]:
    """纯函数校验；不修改传入状态。"""
    raw = cast(Mapping[str, Any], state)
    issues: list[StateIssue] = []

    # 1. 存在性
    for field in required:
        if not _present(raw, field):
            issues.append(_issue(E1_MISSING[field], 1, field, messages.MISSING_REQUIRED))
    for field in optional:
        if not _present(raw, field):
            issues.append(_issue(E2_MISSING[field], 2, field, messages.MISSING_OPTIONAL))

    # 2. 类型 / 3. 取值范围（按文档字段顺序）
    for field in BUSINESS_FIELDS:
        if field in raw and raw[field] is not None:
            issue = _format_issue(field, raw[field])
            if issue is not None:
                issues.append(issue)
    for key, allowed in ROUTE_VALUES.items():
        if key in raw and not _valid_route(raw[key], allowed):
            issues.append(_issue(E2_SCHEMA_ROUTE, 2, key, messages.SCHEMA_ROUTE))

    # 4. 未登记字段（R3.4）
    for key in raw:
        if key not in _KNOWN_FIELDS:
            issues.append(_issue(E2_UNKNOWN_FIELD, 2, key, messages.UNKNOWN_STATE_FIELD))

    issues.extend(_cross_field_issues(raw))
    return issues


def _cross_field_issues(raw: Mapping[str, Any]) -> list[StateIssue]:
    """条件性待选缺失：10/11 非 0 时 3/5/6/7/8 必须可用。"""
    issues: list[StateIssue] = []
    counters_active = any(
        _is_int(raw.get(key)) and cast(int, raw[key]) > 0 for key in ("tsc_count", "m_count")
    )
    if not counters_active:
        return issues
    for field in (
        "optimized_prompt",
        "subtasks",
        "questions",
        "heuristic_score",
        "execution_score",
    ):
        if not _present(raw, field):
            issues.append(
                _issue(
                    E2_CONDITIONAL_MISSING[field],
                    2,
                    field,
                    messages.CONDITIONAL_MISSING,
                )
            )
    return issues


def fatal_issues(issues: list[StateIssue]) -> list[StateIssue]:
    """筛出 1 级错误。"""
    return [issue for issue in issues if issue.level == 1]

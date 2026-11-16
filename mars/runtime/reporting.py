"""Output 报告渲染：纯函数，输入最终 State 快照。"""

from mars.graph.state.constants import M_MAX, TSC_MAX
from mars.graph.state.models import Question, ScoreDetail, Subtask
from mars.graph.state.schema import GraphState


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def acceptance_of(state: GraphState, *, m_max: int = M_MAX) -> str:
    """由终态推导验收结论；供报告与运行列表共用。"""
    if state.get("route_manager") == "output" and state.get("m_count", 0) >= m_max:
        return "未通过（M 超限/未通过验收）"
    if state.get("route_target") == "output":
        return "通过"
    if state.get("route_target") == "manager":
        return "未通过（进入 Manager 回退）"
    return "未知（未执行到验收）"


def _score_line(label: str, detail: ScoreDetail | None) -> str:
    if detail is None:
        return f"- {label}：缺失"
    dimensions = "、".join(f"{key}={value}" for key, value in detail.get("dimensions", {}).items())
    return f"- {label}：{detail['score']}（{dimensions or '无维度'}）；{_cell(detail['summary'])}"


def _subtask_table(items: list[Subtask]) -> str:
    if not items:
        return "（空列表，无可处理项）"
    rows = ["| id | 内容 | 状态 | 得分 |", "| --- | --- | --- | --- |"]
    rows.extend(
        f"| {item['id']} | {_cell(item['content'])} | {item['status']} | {item['score']} |"
        for item in items
    )
    return "\n".join(rows)


def _question_table(items: list[Question]) -> str:
    if not items:
        return "（空列表，无可处理项）"
    rows = ["| id | 内容 | 目标子任务 | 状态 | 得分 |", "| --- | --- | --- | --- | --- |"]
    rows.extend(
        f"| {item['id']} | {_cell(item['content'])} | {item.get('target_task_id') or '-'}"
        f" | {item['status']} | {item['score']} |"
        for item in items
    )
    return "\n".join(rows)


def render_report(state: GraphState, *, tsc_max: int = TSC_MAX, m_max: int = M_MAX) -> str:
    """生成 md 报告；不修改状态，不访问外部资源。"""
    tsc_count = state.get("tsc_count", 0)
    m_count = state.get("m_count", 0)
    flags: list[str] = []
    if tsc_count >= tsc_max:
        flags.append("TSC 超限")
    if m_count >= m_max:
        flags.append("M 超限")
    flag_text = f"（{'、'.join(flags)}）" if flags else ""

    prompt = state.get("optimized_prompt") or ""
    return "\n".join(
        [
            "# 提示词优化报告",
            "",
            "## 优化方向",
            "",
            state.get("optimization_goal") or "（缺失）",
            "",
            "## 验收结论",
            "",
            f"{acceptance_of(state, m_max=m_max)}{flag_text}",
            "",
            "## 循环情况",
            "",
            f"- TSC 循环：{tsc_count}/{tsc_max}",
            f"- M 循环：{m_count}/{m_max}",
            "",
            "## 评分摘要",
            "",
            _score_line("启发得分", state.get("heuristic_score")),
            _score_line("执行得分", state.get("execution_score")),
            "",
            "## 子任务",
            "",
            _subtask_table(state.get("subtasks") or []),
            "",
            "## 启发式提问",
            "",
            _question_table(state.get("questions") or []),
            "",
            "## 最终提示词",
            "",
            "````text",
            prompt,
            "````",
            "",
        ]
    )

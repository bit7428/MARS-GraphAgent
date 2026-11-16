"""状态元素模型：全部为 JSON 可序列化的 TypedDict。"""

from typing import Literal, TypedDict


class IssueDict(TypedDict):
    """可写入 trace 的报错条目。"""

    code: str
    level: int
    field: str | None
    message: str


class Subtask(TypedDict):
    """子任务元素。status=dropped 仅表示划去，记录必须保留。"""

    id: str
    content: str
    source: Literal["planner", "critic", "user"]
    status: Literal["pending", "done", "dropped"]
    score: int


class Question(TypedDict):
    """启发式提问元素。追加必须生成新 id。"""

    id: str
    content: str
    target_task_id: str | None
    status: Literal["open", "resolved", "dropped"]
    score: int


class ScoreDetail(TypedDict):
    """启发/执行得分及摘要；summary 必须含分数变化原因。"""

    score: int
    dimensions: dict[str, int]
    summary: str
    evidence: list[str]


class PerformanceCriterion(TypedDict):
    """验收性能指标，初始化后只读。"""

    name: str
    threshold: float
    comparator: Literal["gte", "lte", "eq"]


class NodeTrace(TypedDict, total=False):
    """单次节点执行追踪；断点事件复用同一结构并标记人工介入。"""

    node: str
    started_at: str
    duration_ms: float
    model: str | None
    prompt_version: str | None
    issues: list[IssueDict]
    writes: list[str]
    side_effects: list[str]
    summary: str
    human_intervention: bool
    original_route: str | None
    new_route: str | None
    operator: str | None
    at: str | None

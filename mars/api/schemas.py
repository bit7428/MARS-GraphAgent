"""API DTO：只做边界校验与转换，不承载业务逻辑。"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mars.config.settings import NodeLLMConfig


class CriterionDTO(BaseModel):
    """单条性能指标 DTO。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    threshold: float
    comparator: Literal["gte", "lte", "eq"]


class RunCreateRequest(BaseModel):
    """创建运行请求。"""

    model_config = ConfigDict(extra="forbid")

    initial_prompt: str = Field(min_length=1)
    optimization_goal: str = Field(min_length=1)
    performance_criteria: list[CriterionDTO] = Field(min_length=1)
    breakpoints: list[str] = Field(default_factory=list)


class RunCreated(BaseModel):
    """创建运行响应。"""

    thread_id: str


class BreakpointUpdateRequest(BaseModel):
    """断点集合替换请求。"""

    model_config = ConfigDict(extra="forbid")

    edge_ids: list[str] = Field(default_factory=list)


class ResumeRequest(BaseModel):
    """断点恢复请求。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "reroute", "abort"]
    target: str | None = None
    operator: str | None = None
    initial_prompt: str | None = None
    optimization_goal: str | None = None
    supplement_mode: Literal["append", "replace"] = "append"

    @model_validator(mode="after")
    def _check_reroute(self) -> Self:
        if self.action == "reroute" and not self.target:
            raise ValueError("reroute 必须提供 target")
        return self

    def decision(self) -> dict[str, Any]:
        """转换为断点恢复载荷。"""
        return {"action": self.action, "target": self.target, "operator": self.operator}

    def supplement(self) -> dict[str, str] | None:
        """转换为 User 节点可消费的补充输入。"""
        payload: dict[str, str] = {}
        if self.initial_prompt:
            payload["initial_prompt"] = self.initial_prompt
        if self.optimization_goal:
            payload["optimization_goal"] = self.optimization_goal
        if not payload:
            return None
        payload["mode"] = self.supplement_mode
        return payload


class StateView(BaseModel):
    """运行状态快照。"""

    thread_id: str
    status: str
    next: list[str]
    interrupts: list[Any]
    values: dict[str, Any]


class EdgeView(BaseModel):
    """边表项。"""

    edge_id: str
    source: str
    target: str
    kind: Literal["static", "conditional"]
    condition: str
    side_effects: list[str]
    breakpoint: bool


class NodeConfigView(BaseModel):
    """节点配置只读视图。"""

    node: str
    model: str
    base_url: str | None
    api_key_env: str
    temperature: float
    timeout_s: float
    max_retries: int
    prompt_version: str

    @classmethod
    def from_config(cls, node: str, config: NodeLLMConfig) -> "NodeConfigView":
        """由内部配置构造只读视图，不暴露密钥。"""
        return cls(node=node, **config.model_dump())


class NodeConfigUpdate(BaseModel):
    """节点配置局部更新。"""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    timeout_s: float | None = Field(default=None, gt=0.0)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    prompt_version: str | None = Field(default=None, pattern=r"^v\d+$")

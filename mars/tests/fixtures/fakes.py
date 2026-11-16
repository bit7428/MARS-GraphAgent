"""测试用 LLM 适配器与配置。"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from mars.config.settings import NodeLLMConfig
from mars.graph.state.schema import GraphState
from mars.llm.adapter import ChatMessage, Completion
from mars.runtime.reporting import render_report
from mars.utils.clock import SequentialIdGenerator


class FixedClock:
    """固定时钟，保证 trace 可复现。"""

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return 100.0


class ScriptedAdapter:
    """按顺序返回脚本响应；元素可为 dict、原始文本或异常。"""

    def __init__(self, responses: list[dict[str, Any] | str | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        config: NodeLLMConfig,
    ) -> Completion:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("没有更多脚本响应")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return Completion(text=text, model="fake")


Handler = Callable[[str], dict[str, Any]] | dict[str, Any]
HandlerSpec = Handler | list[Handler]


class LabeledAdapter:
    """按用户消息中的字段标签选择响应，适配循环场景。"""

    def __init__(self, handlers: dict[str, HandlerSpec]) -> None:
        self.handlers = handlers
        self.calls: list[str] = []

    def complete(
        self,
        messages: list[ChatMessage],
        config: NodeLLMConfig,
    ) -> Completion:
        body = messages[-1]["content"]
        label = _detect_label(body)
        self.calls.append(label)
        spec = self.handlers[label]
        if isinstance(spec, list):
            handler = spec[0]
            if len(spec) > 1:
                spec.pop(0)
        else:
            handler = spec
        payload = handler(body) if callable(handler) else handler
        return Completion(text=json.dumps(payload, ensure_ascii=False), model="fake")


def _detect_label(body: str) -> str:
    if "验收未通过" in body:
        return "manager"
    if "【性能指标】" in body:
        return "target"
    if "【已有提问】" in body:
        return "teacher"
    if "【子任务列表】\n" in body and "【启发式提问列表】" in body:
        return "critic"
    if "【启发式提问列表】" in body:
        return "student"
    if "【现有子任务（参考）】" in body:
        return "planner"
    raise AssertionError("无法识别节点请求")


def make_config(
    adapter: object,
    *,
    breakpoints: set[str] | None = None,
    **overrides: Any,
) -> RunnableConfig:
    configurable: dict[str, Any] = {
        "thread_id": "test-thread",
        "clock": FixedClock(),
        "id_generator": SequentialIdGenerator(),
        "llm_adapter": adapter,
        "report_renderer": render_report,
        "node_configs": {},
        "breakpoints": breakpoints or set(),
    }
    configurable.update(overrides)
    return cast(
        RunnableConfig,
        {"configurable": configurable, "recursion_limit": 200},
    )


def auto_critic(body: str, *, passed: bool, value: int = 100) -> dict[str, Any]:
    """从请求正文提取全部 id，给出可让列表清空的评分。"""
    ids = re.findall(r"- ([sq]\d+)｜", body)
    subtasks = [{"id": item, "score": value} for item in ids if item.startswith("s")]
    questions = [{"id": item, "score": value} for item in ids if item.startswith("q")]
    return {
        "subtask_scores": subtasks,
        "question_scores": questions,
        "heuristic": {
            "score": value,
            "dimensions": {"clarity": value},
            "summary": "提问清晰",
            "evidence": [item["id"] for item in questions],
        },
        "execution": {
            "score": value,
            "dimensions": {"coverage": value},
            "summary": "执行有效",
            "evidence": [],
        },
        "passed": passed,
        "reason": "测试判定",
    }


def target_handler(*, passed: bool) -> dict[str, Any]:
    return {
        "criteria": [{"name": "正确性", "passed": passed, "reason": "测试"}],
        "passed": passed,
        "reason": "测试验收",
    }


def planner_handler(body: str) -> dict[str, Any]:
    return {"working_prompt": "规划后的提示词", "subtasks": [{"content": "规划子任务"}]}


def teacher_handler(body: str) -> dict[str, Any]:
    return {"questions": [{"content": "苏格拉底式提问", "target_task_id": "s001"}]}


def student_handler(body: str) -> dict[str, Any]:
    return {"optimized_prompt": "学生优化后的提示词"}


def manager_handler(target: str) -> dict[str, Any]:
    return {
        "user_defect": target == "user",
        "planner_defect": target == "planner",
        "teacher_defect": target == "teacher",
        "reason": "测试回退",
    }


def default_handlers(
    *,
    critic_passed: bool = True,
    target_passed: bool = True,
    manager_target: str = "teacher",
) -> dict[str, HandlerSpec]:
    return {
        "planner": planner_handler,
        "teacher": teacher_handler,
        "student": student_handler,
        "critic": lambda body: auto_critic(body, passed=critic_passed),
        "target": target_handler(passed=target_passed),
        "manager": manager_handler(manager_target),
    }


def state_invoke(
    fn: Callable[[GraphState, RunnableConfig], dict[str, Any]],
    state: GraphState,
    adapter: object,
    **overrides: Any,
) -> dict[str, Any]:
    return fn(state, make_config(adapter, **overrides))

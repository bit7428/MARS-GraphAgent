"""节点共享上下文构造：显式裁剪输入，禁止整体投喂状态。"""

from collections.abc import Sequence
from typing import TypeVar, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from mars.graph.contract import configurable, node_llm_config
from mars.graph.state.constants import LOW_SCORE_THRESHOLD
from mars.graph.state.models import (
    PerformanceCriterion,
    Question,
    ScoreDetail,
    Subtask,
)
from mars.graph.state.schema import GraphState
from mars.llm.adapter import ChatMessage, adapter_from
from mars.llm.prompts import load_prompt
from mars.llm.structured import StructuredResult, request_structured

TModel = TypeVar("TModel", bound=BaseModel)
TItem = TypeVar("TItem")

MAX_TEXT_CHARS = 4000
MAX_LIST_ITEMS = 20


def truncate(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    """裁剪长文本，避免上下文膨胀。"""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（已截断）"


def _limited(items: Sequence[TItem]) -> Sequence[TItem]:
    return items[:MAX_LIST_ITEMS]


def format_subtasks(subtasks: Sequence[Subtask]) -> str:
    """格式化子任务摘要，限制条数与单条长度。"""
    if not subtasks:
        return "（空列表，无可处理项）"
    lines = [
        f"- {item['id']}｜{item['status']}｜{item['score']}｜{truncate(item['content'], 300)}"
        for item in _limited(subtasks)
    ]
    return "\n".join(lines)


def format_questions(questions: Sequence[Question]) -> str:
    """格式化提问摘要，限制条数与单条长度。"""
    if not questions:
        return "（空列表，无可处理项）"
    lines = [
        f"- {item['id']}｜{item['status']}｜{item['score']}"
        f"｜目标:{item.get('target_task_id') or '-'}"
        f"｜{truncate(item['content'], 300)}"
        for item in _limited(questions)
    ]
    return "\n".join(lines)


def format_score(label: str, detail: ScoreDetail | None) -> str:
    """格式化得分与变化摘要。"""
    if detail is None:
        return f"【{label}】缺失"
    dimensions = "，".join(f"{key}={value}" for key, value in detail.get("dimensions", {}).items())
    return (
        f"【{label}】{detail['score']}（{dimensions or '无维度'}）\n"
        f"摘要：{truncate(detail['summary'], 500)}"
    )


def format_criteria(criteria: Sequence[PerformanceCriterion]) -> str:
    """格式化性能指标。"""
    return "\n".join(
        f"- {item['name']}｜{item['comparator']}｜{item['threshold']}" for item in criteria
    )


def low_dimension_hint(state: GraphState) -> str:
    """7/8 低于 60 时，提示优先聚焦低分维度。"""
    hints: list[str] = []
    for label, key in (("启发得分", "heuristic_score"), ("执行得分", "execution_score")):
        detail = cast(ScoreDetail | None, state.get(key))
        if detail is None or detail["score"] >= LOW_SCORE_THRESHOLD:
            continue
        low = [
            name
            for name, value in detail.get("dimensions", {}).items()
            if value < LOW_SCORE_THRESHOLD
        ]
        hints.append(f"{label}低于{LOW_SCORE_THRESHOLD}，低分维度：{'、'.join(low) or '未标注'}")
    return "；".join(hints) if hints else "无"


def build_messages(config: RunnableConfig, node: str, body: str) -> list[ChatMessage]:
    """系统提示词外置；正文只含显式裁剪后的业务字段。"""
    model_config = node_llm_config(config, node)
    system_prompt = load_prompt(node, model_config.prompt_version)
    messages: list[ChatMessage] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": body})
    return messages


def call_structured(
    config: RunnableConfig,
    *,
    node: str,
    body: str,
    schema: type[TModel],
) -> StructuredResult[TModel]:
    """经适配器调用 LLM，并走结构化解析与有限重试。"""
    model_config = node_llm_config(config, node)
    adapter = adapter_from(configurable(config))
    return request_structured(
        adapter,
        messages=build_messages(config, node, body),
        schema=schema,
        config=model_config,
    )

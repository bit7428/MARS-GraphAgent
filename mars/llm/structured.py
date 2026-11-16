"""结构化输出：解析 → 校验 → 有限重试 → 抛出。"""

import json
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from mars.config.settings import NodeLLMConfig
from mars.graph.state.errors import LLMError, StructuredOutputError
from mars.llm.adapter import ChatAdapter, ChatMessage

TModel = TypeVar("TModel", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class StructuredResult(Generic[TModel]):
    """结构化结果与追踪元信息。"""

    data: TModel
    model: str
    prompt_version: str
    attempts: int


def _extract_object(text: str) -> str:
    cleaned = _FENCE.sub("", text.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("响应中没有 JSON 对象")
    return cleaned[start : end + 1]


def request_structured(
    adapter: ChatAdapter,
    *,
    messages: list[ChatMessage],
    schema: type[TModel],
    config: NodeLLMConfig,
) -> StructuredResult[TModel]:
    """有限重试；重试只改消息，不产生状态写入。"""
    conversation = list(messages)
    last_error: Exception | None = None
    attempts = max(1, config.max_retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            completion = adapter.complete(conversation, config)
        except LLMError:
            raise
        try:
            payload = json.loads(_extract_object(completion.text))
            data = schema.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            last_error = exc
            conversation = [
                *conversation,
                {"role": "assistant", "content": completion.text},
                {
                    "role": "user",
                    "content": "输出不符合约定的 JSON schema，请只返回合法 JSON 后重试。",
                },
            ]
            continue
        return StructuredResult(
            data=data,
            model=completion.model,
            prompt_version=config.prompt_version,
            attempts=attempt,
        )
    raise StructuredOutputError(f"结构化输出失败: {type(last_error).__name__}")

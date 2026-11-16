"""LLM 调用唯一入口：只接收 messages 与节点配置，不感知业务字段。"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, cast

from pydantic import SecretStr

from mars import messages as msgs
from mars.config.settings import NodeLLMConfig
from mars.graph.state.errors import LLMError


class ChatMessage(TypedDict):
    """一条聊天消息。"""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    """一次原始补全结果。"""

    text: str
    model: str


class ChatAdapter(Protocol):
    """可替换的补全适配器；测试注入假实现。"""

    def complete(
        self,
        messages: list[ChatMessage],
        config: NodeLLMConfig,
    ) -> Completion:
        """返回一次原始补全。"""
        ...


class OpenAICompatAdapter:
    """OpenAI 兼容接口实现；密钥仅从指定环境变量读取。"""

    def complete(
        self,
        messages: list[ChatMessage],
        config: NodeLLMConfig,
    ) -> Completion:
        """调用 OpenAI 兼容接口并返回文本。"""
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise LLMError(msgs.LLM_MISSING_KEY.format(name=config.api_key_env))
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - 依赖缺失属环境问题
            raise LLMError(msgs.LLM_IMPORT_FAILED) from exc

        llm = ChatOpenAI(
            model=config.model,
            base_url=config.base_url,
            api_key=SecretStr(api_key),
            temperature=config.temperature,
            timeout=config.timeout_s,
            max_retries=0,
        )
        factories = {
            "system": SystemMessage,
            "user": HumanMessage,
            "assistant": AIMessage,
        }
        payload = [factories[message["role"]](content=message["content"]) for message in messages]
        try:
            response = llm.invoke(payload)
        except Exception as exc:
            raise LLMError(msgs.LLM_CALL_FAILED.format(error=type(exc).__name__)) from exc
        content = response.content
        text = content if isinstance(content, str) else str(content)
        return Completion(text=text, model=config.model)


def adapter_from(configurable: Mapping[str, object]) -> ChatAdapter:
    """读取注入的适配器，否则使用默认 OpenAI 兼容实现。"""
    injected = configurable.get("llm_adapter")
    if injected is not None:
        return cast(ChatAdapter, injected)
    return OpenAICompatAdapter()

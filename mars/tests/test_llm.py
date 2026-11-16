"""LLM 边界与配置测试。"""

import pytest

from mars.config.settings import NodeConfigStore, NodeLLMConfig, NodeOverride
from mars.graph.state.errors import LLMError
from mars.llm.adapter import OpenAICompatAdapter, adapter_from
from mars.llm.prompts import PromptNotFoundError, load_prompt
from mars.tests.fixtures.fakes import ScriptedAdapter


def _config() -> NodeLLMConfig:
    return NodeLLMConfig(model="fake", api_key_env="MARS_TEST_MISSING_KEY")


def test_adapter_requires_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARS_TEST_MISSING_KEY", raising=False)
    with pytest.raises(LLMError):
        OpenAICompatAdapter().complete([{"role": "user", "content": "hi"}], _config())


def test_adapter_from_injected() -> None:
    injected = ScriptedAdapter([])
    assert adapter_from({"llm_adapter": injected}) is injected


_PROMPT_NODES = ("planner", "teacher", "student", "critic", "target", "manager")
_PROMPT_SECTIONS = ("角色", "职责", "职责边界", "输出规范", "约束")


def test_prompt_files_define_node_contracts() -> None:
    """六个 LLM 节点的系统提示词必须存在且覆盖规范要求的章节。"""
    for node in _PROMPT_NODES:
        text = load_prompt(node, "v1")
        assert text.strip(), f"{node} 提示词为空"
        for section in _PROMPT_SECTIONS:
            assert section in text, f"{node} 提示词缺少「{section}」章节"
        assert "JSON" in text, f"{node} 提示词未约定 JSON 输出"


def test_prompt_version_is_validated() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("planner", "../../etc")
    with pytest.raises(PromptNotFoundError):
        load_prompt("planner", "v99")


def test_node_config_store_merges_and_resets() -> None:
    store = NodeConfigStore()
    original = store.node_config("planner")
    updated = store.update("planner", NodeOverride(model="changed", temperature=0.9))
    assert updated.model == "changed"
    assert updated.temperature == 0.9
    assert store.snapshot()["planner"].model == "changed"
    assert store.reset("planner").model == original.model

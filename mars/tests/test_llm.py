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


def test_prompt_files_are_empty_placeholders() -> None:
    for node in ("planner", "teacher", "student", "critic", "target", "manager"):
        assert load_prompt(node, "v1") == ""


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

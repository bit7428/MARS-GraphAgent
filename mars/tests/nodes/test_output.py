"""Output 节点测试。"""

import pytest

from mars.graph.nodes.output import run_output
from mars.graph.state.errors import CodingContractError, FatalStateError
from mars.tests.fixtures.fakes import ScriptedAdapter, state_invoke
from mars.tests.fixtures.states import base_state, without_state


def test_output_renders_report() -> None:
    result = state_invoke(run_output, base_state(), ScriptedAdapter([]))
    report = result["report_md"]
    assert "# 提示词优化报告" in report
    assert "已优化提示词" in report
    assert result["trace"][0]["node"] == "output"


def test_output_requires_renderer() -> None:
    with pytest.raises(CodingContractError):
        state_invoke(run_output, base_state(), ScriptedAdapter([]), report_renderer=None)


def test_output_missing_prompt_is_fatal() -> None:
    with pytest.raises(FatalStateError):
        state_invoke(run_output, without_state("optimized_prompt"), ScriptedAdapter([]))

"""节点契约测试。"""

from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig

from mars.graph.contract import make_trace, node_contract, session_of
from mars.graph.state.errors import CodingContractError, FatalStateError
from mars.graph.state.models import Subtask
from mars.graph.state.schema import GraphState
from mars.tests.fixtures.fakes import ScriptedAdapter, make_config
from mars.tests.fixtures.states import base_state


def _trace(config: RunnableConfig, node: str, writes: tuple[str, ...]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        make_trace(
            session_of(config),
            node=node,
            summary="测试",
            writes=writes,
        ),
    )


def test_out_of_contract_write_is_rejected() -> None:
    @node_contract(node="custom-extra", writes=())
    def bad(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        return {"unknown": 1, "trace": [_trace(config, "custom-extra", ())]}

    with pytest.raises(CodingContractError):
        bad(base_state(), make_config(ScriptedAdapter([])))


def test_missing_trace_is_rejected() -> None:
    @node_contract(node="custom-no-trace", writes=("optimized_prompt",))
    def bad(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        return {"optimized_prompt": "x"}

    with pytest.raises(CodingContractError):
        bad(base_state(), make_config(ScriptedAdapter([])))


def test_in_place_mutation_is_rejected() -> None:
    @node_contract(node="custom-mut", writes=("optimized_prompt",))
    def bad(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        state["subtasks"].append(
            cast(
                Subtask,
                {"id": "s999", "content": "x", "source": "user", "status": "pending", "score": 0},
            )
        )
        return {
            "optimized_prompt": "x",
            "trace": [_trace(config, "custom-mut", ("optimized_prompt",))],
        }

    with pytest.raises(CodingContractError):
        bad(base_state(), make_config(ScriptedAdapter([])))


def test_performance_criteria_is_read_only() -> None:
    @node_contract(node="custom-criteria", writes=("performance_criteria",))
    def bad(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        return {
            "performance_criteria": [],
            "trace": [_trace(config, "custom-criteria", ("performance_criteria",))],
        }

    with pytest.raises(CodingContractError):
        bad(base_state(), make_config(ScriptedAdapter([])))


def test_fatal_error_prevents_writes() -> None:
    @node_contract(node="custom-fatal", required=("initial_prompt",))
    def bad(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        return {"trace": [_trace(config, "custom-fatal", ())]}

    with pytest.raises(FatalStateError):
        bad(cast(GraphState, {}), make_config(ScriptedAdapter([])))


def test_trace_has_required_fields() -> None:
    @node_contract(node="custom-trace", writes=("optimized_prompt",))
    def ok(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
        return {
            "optimized_prompt": "x",
            "trace": [_trace(config, "custom-trace", ("optimized_prompt",))],
        }

    result = ok(base_state(), make_config(ScriptedAdapter([])))
    trace = result["trace"][0]
    for field in (
        "node",
        "started_at",
        "duration_ms",
        "model",
        "prompt_version",
        "issues",
        "writes",
        "side_effects",
        "summary",
    ):
        assert field in trace

"""Output 节点：触发报告渲染并截取最终提示词，不改业务字段。"""

from collections.abc import Callable
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from mars import messages
from mars.graph.contract import configurable, make_trace, node_contract, session_of
from mars.graph.state.errors import CodingContractError
from mars.graph.state.schema import GraphState


@node_contract(
    node="output",
    required=("optimized_prompt",),
    writes=("report_md",),
)
def run_output(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Output：生成 md 报告并输出 3. 已优化提示词。

    接收：全局状态。
    更新：不修改业务字段；写 report_md。
    报错：缺失 3. 为 1 级；格式不规范为 2 级。
    """
    renderer = configurable(config).get("report_renderer")
    if not callable(renderer):
        raise CodingContractError("Output 需要注入 report_renderer")
    report = cast(Callable[[GraphState], str], renderer)(state)
    session = session_of(config)
    trace = make_trace(
        session,
        node="output",
        summary=messages.OUTPUT_SUMMARY,
        writes=("report_md",),
    )
    return {"report_md": report, "trace": [trace]}

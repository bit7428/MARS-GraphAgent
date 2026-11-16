"""checkpointer 装配；当前仅支持进程内存。"""

from langgraph.checkpoint.memory import InMemorySaver


def build_checkpointer() -> InMemorySaver:
    """单进程内存检查点，重启后丢失，符合当前能力边界。"""
    return InMemorySaver()

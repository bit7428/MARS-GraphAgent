"""演示适配器：无需外网与密钥即可完整跑通 8 节点流程。

仅在 `MARS_DEMO=1` 时由 API 装配；生产路径仍走 OpenAI 兼容适配器。
输出为确定性的中文样例，用于验证前端状态图、断点与报告。
"""

import json
import re
from typing import Any

from mars.config.settings import NodeLLMConfig
from mars.llm.adapter import ChatMessage, Completion

_SUBTASK_ID = re.compile(r"- (s\d+)｜")
_QUESTION_ID = re.compile(r"- (q\d+)｜")
_CRITERION = re.compile(r"^- (.+?)｜(gte|lte|eq)｜", re.MULTILINE)


class DemoAdapter:
    """按节点与调用轮次返回样例 JSON；每轮运行前重置计数。

    profile="fail" 时 Target 永远不通过，用于演示 M 超限失败报告。
    """

    def __init__(self, profile: str = "default") -> None:
        self._profile = profile
        self._counts: dict[str, int] = {}

    def begin_run(self) -> None:
        """新一轮运行重置轮次，保证同一演示可重复。"""
        self._counts.clear()

    def complete(
        self,
        messages: list[ChatMessage],
        config: NodeLLMConfig,
    ) -> Completion:
        """返回一次确定性补全。"""
        body = messages[-1]["content"]
        node = _detect_node(body)
        round_index = self._counts.get(node, 0) + 1
        self._counts[node] = round_index
        payload = _payload(node, round_index, body, self._profile)
        return Completion(
            text=json.dumps(payload, ensure_ascii=False),
            model=f"demo/{config.model}",
        )


def _detect_node(body: str) -> str:
    if "验收未通过" in body:
        return "manager"
    if "【性能指标】" in body:
        return "target"
    if "【现有子任务（参考）】" in body:
        return "planner"
    if "【已有提问】" in body:
        return "teacher"
    if "【子任务列表】" in body and "【启发式提问列表】" in body:
        return "critic"
    if "【启发式提问列表】" in body:
        return "student"
    raise AssertionError("无法识别的节点请求")


def _section(body: str, label: str) -> str:
    """截取 `【label】` 之后、下一个区块之前的正文。"""
    marker = f"【{label}】"
    start = body.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = body.find("\n\n【", start)
    chunk = body[start:end] if end >= 0 else body[start:]
    return chunk.strip()


def _payload(node: str, round_index: int, body: str, profile: str) -> dict[str, Any]:
    if node == "planner":
        return _planner(body)
    if node == "teacher":
        return _teacher(round_index, body)
    if node == "student":
        return _student(body)
    if node == "critic":
        return _critic(round_index, body)
    if node == "target":
        return _target(round_index, body, profile)
    return _manager()


def _planner(body: str) -> dict[str, Any]:
    initial = _section(body, "初始提示词") or "（未提供初始提示词）"
    goal = _section(body, "优化方向及目的") or "提升可执行性"
    working = (
        "# 任务\n"
        f"{initial}\n\n"
        "# 优化目标\n"
        f"{goal}\n\n"
        "# 输出要求\n"
        "1. 严格按约定结构输出，不添加额外解释；\n"
        "2. 所有字段必须填写，缺失时写“未知”；\n"
        "3. 使用简体中文，避免口语化表达。"
    )
    return {
        "working_prompt": working,
        "subtasks": [
            {"content": "固定输出结构：明确字段名、顺序与类型"},
            {"content": "补齐异常场景的处理口径与兜底话术"},
            {"content": "约束语气、长度与术语一致性"},
        ],
    }


def _teacher(round_index: int, body: str) -> dict[str, Any]:
    subtasks = _SUBTASK_ID.findall(body)
    anchor = subtasks[0] if subtasks else None
    existing = _section(body, "已有提问")
    candidates = [
        "当前提示词是否明确了输出的字段顺序与取值范围？",
        "当输入缺少关键信息（如订单号）时，提示词要求模型如何兜底？",
    ]
    if round_index >= 2:
        candidates.append("上一轮执行得分偏低，是否应补充一个正例与一个反例？")
    fresh = [text for text in candidates if text not in existing]
    return {
        "questions": [{"content": text, "target_task_id": anchor} for text in fresh],
    }


def _core_task(working: str) -> str:
    """从已包装过的提示词中取出核心任务，避免多轮循环后层层嵌套。"""
    marker = "# 任务\n"
    start = working.find(marker)
    if start < 0:
        return working.strip()
    start += len(marker)
    end = working.find("\n\n# ", start)
    return (working[start:end] if end >= 0 else working[start:]).strip()


def _student(body: str) -> dict[str, Any]:
    working = _core_task(_section(body, "待优化提示词"))
    if not working or working == "（空列表，无可处理项）":
        working = "按用户输入完成结构化分析。"
    template = (
        "# 角色\n"
        "你是一名严谨的业务分析助手，只依据给定输入工作，不引入外部假设。\n\n"
        "# 任务\n"
        "{working}\n\n"
        "# 执行步骤\n"
        "1. 通读输入，识别缺失字段；无法确定时输出“未知”，禁止编造。\n"
        "2. 按固定结构输出：summary / category / confidence / actions。\n"
        "3. 每条 actions 给出触发条件与兜底话术。\n"
        "4. 输出前自检：字段齐全、术语一致、无口语化表达。\n\n"
        "# 输出格式\n"
        '```json\n{"summary": "string", "category": "string", '
        '"confidence": 0.0, "actions": [{"trigger": "string", "reply": "string"}]}\n```\n\n'
        "# 约束\n"
        "- 不使用“可能”“大概”等模糊表述；\n"
        "- 单条 reply 不超过 80 字；\n"
        "- 涉及金额与时限必须原样引用输入。"
    )
    return {"optimized_prompt": template.replace("{working}", working)}


def _critic(round_index: int, body: str) -> dict[str, Any]:
    subtask_ids = _SUBTASK_ID.findall(body)
    question_ids = _QUESTION_ID.findall(body)
    if round_index <= 1:
        subtask_score, question_score, heuristic, execution, passed = 72, 55, 58, 61, False
        summary = "结构与目标已对齐，但异常兜底缺失，可执行性偏低"
    elif round_index == 2:
        subtask_score, question_score, heuristic, execution, passed = 80, 64, 74, 72, False
        summary = "提问已覆盖异常场景，子任务仍未闭环"
    else:
        subtask_score, question_score, heuristic, execution, passed = 92, 74, 88, 86, True
        summary = "子任务全部闭环，提问均已解答，整体满足验收标准"
    return {
        "subtask_scores": [{"id": item, "score": subtask_score} for item in subtask_ids],
        "question_scores": [{"id": item, "score": question_score} for item in question_ids],
        "heuristic": {
            "score": heuristic,
            "dimensions": {"clarity": heuristic, "depth": max(0, heuristic - 6)},
            "summary": summary,
            "evidence": question_ids[:2] or subtask_ids[:1] or ["none"],
        },
        "execution": {
            "score": execution,
            "dimensions": {"coverage": execution, "consistency": max(0, execution - 4)},
            "summary": summary,
            "evidence": [],
        },
        "passed": passed,
        "reason": summary,
    }


def _target(round_index: int, body: str, profile: str) -> dict[str, Any]:
    names = [name for name, _ in _CRITERION.findall(body)] or ["正确性"]
    passed = round_index >= 2 and profile != "fail"
    criteria = [
        {
            "name": name,
            "passed": passed if index == 0 else True,
            "reason": "结构完整且异常场景有兜底" if passed else "缺少异常场景兜底，可执行性不足",
        }
        for index, name in enumerate(names)
    ]
    return {
        "criteria": criteria,
        "passed": passed,
        "reason": "验收通过" if passed else "存在未达标项",
    }


def _manager() -> dict[str, Any]:
    return {
        "user_defect": False,
        "planner_defect": False,
        "teacher_defect": True,
        "reason": "初始方向与子任务基本合理，但执行得分偏低、提问未推进，回退 Teacher",
    }

"""集中管理用户可见文案，节点与运行期不得散落中文提示。"""

# User
USER_RECEIVED = "已接收用户输入"
USER_INCOMPLETE = "用户输入不完整，继续运行并提示补充"
USER_MISSING_INPUT = "初始提示词或优化方向为空，请用户补充"

# Planner
PLANNER_SUMMARY = "生成待优化提示词；新增子任务 {count} 条"
PLANNER_LLM_FAILED = "Planner LLM 失败，回退初始提示词：{error}"

# Teacher
TEACHER_SUMMARY = "追加提问 {count} 条"
TEACHER_EMPTY = "无可处理项，未追加提问"
TEACHER_LLM_FAILED = "Teacher LLM 失败，保留既有提问：{error}"

# Student
STUDENT_SUMMARY = "已生成已优化提示词"
STUDENT_FALLBACK = "LLM 失败，最小响应"
STUDENT_LLM_FAILED = "Student LLM 失败，沿用待优化提示词：{error}"

# Critic
CRITIC_PASS = "满足要求，进入 Target"
CRITIC_TSC_OVER = "TSC 超限（{count}/{maximum}），进入 Target"
CRITIC_LOOP = "未满足要求，进入 TSC 循环（{count}/{maximum}）"
CRITIC_UNKNOWN_IDS = "存在未知 id: {ids}"
CRITIC_MISSING_SCORES = "存在未打分的元素: {ids}"
CRITIC_LLM_FAILED = "Critic LLM 失败，沿用既有评分：{error}"

# Target
TARGET_PASS = "验收通过，进入 Output"
TARGET_FAIL = "验收不通过，进入 Manager"
TARGET_UNDECIDABLE = "验收结论无法生成，默认进入 Manager"
TARGET_MISSING_CRITERIA = "缺少指标结论: {names}"
TARGET_LLM_FAILED = "Target LLM 失败，默认进入 Manager：{error}"

# Output
OUTPUT_SUMMARY = "生成优化报告并截取已优化提示词"

# Manager
MANAGER_FORCE_OUTPUT = "M 超限（{count}/{maximum}），强制进入 Output 并标记未通过"
MANAGER_ROLLBACK = "回退 {target}，M 计数 {count}/{maximum}"
MANAGER_LLM_FAILED = "Manager LLM 失败，保守回退 Teacher：{error}"
MANAGER_DEFAULT_ROUTE = "路由判定缺失，使用默认 teacher"

# 校验
MISSING_REQUIRED = "必填字段缺失或为 null"
MISSING_OPTIONAL = "待选字段缺失或为 null"
CONDITIONAL_MISSING = "循环已启动，条件性待选字段缺失"
SCHEMA_PROMPT = "应为非空字符串"
SCHEMA_SUBTASK = "子任务列表格式不规范"
SCHEMA_QUESTION = "提问列表格式不规范"
SCHEMA_HEURISTIC = "启发得分格式不规范"
SCHEMA_EXECUTION = "执行得分格式不规范"
SCHEMA_CRITERIA = "性能指标格式不规范"
SCHEMA_COUNTER = "应为非负整数"
SCHEMA_ROUTE = "路由键取值非法"
UNKNOWN_STATE_FIELD = "未登记的状态键"

# 断点
GATE_CONTINUE = "人工确认继续原路由"
GATE_ABORT = "人工中止运行"
GATE_INVALID = "恢复载荷非法，保持原路由"
GATE_REROUTE = "人工改道 {original}->{target}"
GATE_REROUTE_REJECTED = "改道到 {target} 被拒绝，保持原路由"
REROUTE_NOT_ALLOWED = "不允许改道到 {target}"
REROUTE_CONTRACT_FAILED = "目标 {target} 契约校验失败: {codes}"
BREAKPOINT_UNKNOWN_ACTION = "未知恢复动作"
BREAKPOINT_BAD_PAYLOAD = "恢复载荷格式非法"

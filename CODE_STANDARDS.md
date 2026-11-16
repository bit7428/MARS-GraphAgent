# MARS-Graph 代码规范（Code Standards）

> 适用范围：本仓库全部 Python 代码、提示词文件、配置与测试。
>
> 文档地位：`MARS-Prompt.md` 是产品与图语义的唯一权威来源；本文件只规定“如何实现”，不改变任何业务语义。
> **冲突时以 `MARS-Prompt.md` 为准**，并立即提交修正本文件的 PR。
> 本规范不得用于修改 `MARS-Prompt.md`。

规范用词：**必须（MUST）** = 违反即拒绝合并；**应当（SHOULD）** = 需在 PR 中说明理由；**禁止（MUST NOT）** = 零容忍。

---

## 1. 技术栈与工程基线

### 1.1 版本基线

| 项 | 要求 |
| --- | --- |
| Python | 3.11+，禁止使用 3.12+ 独有语法 |
| LangGraph | 锁定次版本（`langgraph~=0.6`），升级必须单独 PR |
| 数据校验 | Pydantic v2（仅用于边界层），State 本体用 `TypedDict` |
| 包管理 | `uv` + `pyproject.toml`，提交 `uv.lock` |
| 格式化 / Lint | `ruff format` + `ruff check`，行宽 100 |
| 类型检查 | `mypy --strict`，禁止裸 `Any` |
| 测试 | `pytest` + `pytest-asyncio` |

### 1.2 目录结构（强制）

```
mars/
  graph/
    builder.py            # 仅装配图：add_node / add_edge，禁止业务逻辑
    edge_table.py         # 边表常量，与 MARS-Prompt.md「边表」逐条对应
    nodes/
      user.py planner.py teacher.py student.py critic.py target.py output.py manager.py
    routing/
      critic.py target.py manager.py     # 纯路由函数
    state/
      schema.py           # GraphState（TypedDict）与通道定义
      models.py           # Subtask / Question / ScoreDetail / PerformanceCriterion
      constants.py        # TSC_MAX / M_MAX / 阈值
      validate.py         # 状态校验、字段存在性判定、错误码生成
      errors.py           # FatalStateError / StateIssue / ErrorCode
      reducers.py         # 自定义 reducer
  llm/
    adapter.py            # LLM 调用唯一入口
    structured.py         # 结构化输出解析与重试
  prompts/
    planner/v1.md ...     # 每个节点独立目录 + 版本文件
  runtime/
    runner.py             # 图执行入口、异常收敛
    breakpoints.py        # 断点注入、恢复、人工改道（唯一允许 Command 的位置）
    checkpoint.py         # checkpointer 装配
    reporting.py          # Output 报告渲染（纯函数）
  api/                    # FastAPI：仅做 DTO 转换与流式转发
  config/
    settings.py           # pydantic-settings，环境变量读取
  tests/
    nodes/ routing/ graph/ invariants/ fixtures/
```

### 1.3 依赖方向（禁止反向）

```
api → runtime → graph → state
                 ↓
                llm → prompts
```

- `graph/**` **禁止** import `api/**`、`runtime/**`。
- `state/**` **禁止** import 任何节点、LangGraph、LLM SDK（保持纯数据 + 纯校验）。
- 节点之间**禁止**互相 import；跨节点共享逻辑必须下沉到 `state/**` 或独立 `utils/`。
- `llm/**` **禁止**感知节点名与业务字段，只接收 `messages` 与 `model_config`。

---

## 2. 字段命名：数字 ↔ 代码名（强制映射）

文档中的 1–11 编号只允许出现在注释、日志与文档中。**代码、状态键、日志字段、API 一律使用下列代码名**。

| # | 语义 | 代码名 | 类型 | 业务写者 | 合并方式 |
| --- | --- | --- | --- | --- | --- |
| 1 | 初始提示词 | `initial_prompt` | `str` | User | replace |
| 2 | 待优化提示词 | `working_prompt` | `str` | Planner、Critic(快照) | replace |
| 3 | 已优化提示词 | `optimized_prompt` | `str` | Student、Critic(置空) | replace |
| 4 | 优化方向及目的 | `optimization_goal` | `str` | User | replace |
| 5 | 子任务列表 | `subtasks` | `list[Subtask]` | Planner、Critic | replace（整表替换，禁止原地 append） |
| 6 | 启发式提问列表 | `questions` | `list[Question]` | Teacher、Critic | replace |
| 7 | 启发得分及摘要 | `heuristic_score` | `ScoreDetail \| None` | Critic | replace |
| 8 | 执行得分及摘要 | `execution_score` | `ScoreDetail \| None` | Critic | replace |
| 9 | 性能指标 | `performance_criteria` | `list[PerformanceCriterion]` | **仅入口** | 初始化后只读 |
| 10 | TSC 循环次数 | `tsc_count` | `int` | Critic | replace |
| 11 | M 循环次数 | `m_count` | `int` | Manager | replace |

**非业务通道（必须与业务字段隔离，且写者受限）：**

| 通道 | 代码名 | 类型 | 写者 | 说明 |
| --- | --- | --- | --- | --- |
| 路由键 | `route_critic` / `route_target` / `route_manager` | `Literal` | 对应节点 | 仅供条件边读取，业务逻辑禁止读取 |
| 追踪 | `trace` | `Annotated[list[NodeTrace], operator.add]` | 所有节点 | 每次节点执行追加 **恰好一条** |
| 产物 | `report_md` | `str \| None` | Output | 输出通道，不参与业务校验与节点读取 |

规则：

- R2.1 一个字段只有一个「业务写者」集合；写者由本表穷举，新增写者视为**规范变更**。
- R2.2 `performance_criteria` 必须视为不变量；任何节点返回该键都视为严重缺陷（测试中断言）。
- R2.3 编号与代码名的对应关系只维护在本表与 `graph/state/constants.py`，禁止在代码里散落魔法字符串 `"3"`、`"7"`。
- R2.4 状态键命名一律 `snake_case`，禁止缩写、禁止 `prompt1/prompt2` 之类无语义名称。

---

## 3. State 规范

### 3.1 结构定义

```python
# graph/state/schema.py
from typing import Annotated, Literal, TypedDict
import operator

class GraphState(TypedDict, total=False):
    initial_prompt: str
    working_prompt: str
    optimized_prompt: str
    optimization_goal: str
    subtasks: list[Subtask]
    questions: list[Question]
    heuristic_score: ScoreDetail | None
    execution_score: ScoreDetail | None
    performance_criteria: list[PerformanceCriterion]
    tsc_count: int
    m_count: int

    route_critic: Literal["teacher", "target"]
    route_target: Literal["output", "manager"]
    route_manager: Literal["user", "planner", "teacher", "output"]

    trace: Annotated[list[NodeTrace], operator.add]
    report_md: str | None
```

- R3.1 State 只存 **JSON 可序列化** 数据：`str/int/float/bool/None/list/dict`。禁止存放 LLM 客户端、锁、文件句柄、`datetime` 对象、自定义类实例。
- R3.2 禁止在 State 中存放任何密钥、API Key、请求头、用户凭证；LLM 配置走 `config` / `settings`。
- R3.3 `total=False` 是刻意的：字段缺失与 `None` 是**业务语义**（见 3.3），不得依赖默认值掩盖缺失。
- R3.4 禁止给 State 增加未在本文件登记的键。新增键 = 修改 `MARS-Prompt.md` + 本文件 + `GraphState` 三处同步。

### 3.2 元素模型

```python
class Subtask(TypedDict):
    id: str                 # 稳定唯一，禁止复用已 dropped 的 id
    content: str
    source: Literal["planner", "critic", "user"]
    status: Literal["pending", "done", "dropped"]
    score: int              # 0–100

class Question(TypedDict):
    id: str
    content: str
    target_task_id: str | None
    status: Literal["open", "resolved", "dropped"]
    score: int

class ScoreDetail(TypedDict):
    score: int              # 0–100
    dimensions: dict[str, int]
    summary: str            # 非空，必须包含分数变化原因
    evidence: list[str]     # 7 号必须非空：子任务/提问 id

class PerformanceCriterion(TypedDict):
    name: str
    threshold: float
    comparator: Literal["gte", "lte", "eq"]
```

- R3.5 列表元素只能用 `TypedDict` + `Literal` 建模；Pydantic 模型只出现在 LLM 边界，落库前必须 `.model_dump()`。
- R3.6 `subtasks` / `questions` 是 **append-only 语义**：划去只改 `status`，**禁止物理删除**；追加必须生成新 `id`，禁止覆盖 `resolved` 项。
- R3.7 id 生成必须走 `state/ids.py` 的 `next_id(prefix, existing)`，禁止 `uuid4()` 直接散落（不可复现、不可快照）。

### 3.3 字段存在性与格式校验

严格实现文档语义，禁止“宽松兼容”：

| 判定 | 定义 | 处理 |
| --- | --- | --- |
| 字段缺失 | 键不存在 或 值为 `None` | 按必填/待选分级报错 |
| 空列表 | 键存在且为 `[]` | **视为存在**，不报错，但 trace 必须写“无可处理项” |
| 格式不规范 | 违反文档「状态格式校验最低标准」 | 2 级报错，继续运行 |

校验入口唯一：

```python
def validate_state(state: GraphState, *, required: tuple[str, ...], optional: tuple[str, ...]) -> list[StateIssue]: ...
```

- R3.8 校验逻辑**只允许**存在于 `state/validate.py`；节点内禁止手写 `if not state.get("x")` 之类分散判断。
- R3.9 校验必须是**纯函数、无副作用、幂等**，禁止修改传入状态。
- R3.10 校验顺序固定：存在性 → 类型 → 取值范围 → 跨字段一致性（如 `tsc_count > 0` 时 3/5/6/7/8 的可用性）。

---

## 4. 节点（Node）规范

### 4.1 函数签名与契约

```python
@node_contract(
    required=("working_prompt", "optimization_goal", "questions"),
    optional=("subtasks",),
    writes=("optimized_prompt",),
)
def run_student(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Student：根据 2/4/6 生成 3。

    接收：required 2.4.6.；optional 5.
    更新：3.
    报错：E1-MISSING-2/4/6；E2-MISSING-5；E2-SCHEMA。
    """
```

- R4.1 节点函数命名 `run_<node>`，唯一入参 `(state, config)`，返回值 `dict[str, Any]`（**部分状态**）。
- R4.2 每个节点必须声明三张清单：`required`、`optional`、`writes`，且与 `MARS-Prompt.md` 节点章节逐字对应。
- R4.3 节点**必须**返回部分字典，**禁止**返回完整 State，**禁止**原地修改 `state`（包括嵌套 list/dict）。需要改动列表时构造新列表。
- R4.4 **一次原子更新**：一个节点在一次执行中只返回一个字典。文档中“先…再…”的多步更新必须合并进该字典；禁止拆成多次返回或多次 `update_state`。
- R4.5 返回值键集合 ⊆ `writes ∪ {"trace"}`。越界写入在测试中直接失败（`CodingContractError`）。
- R4.6 节点是**唯一**业务写入点。路由函数、装饰器、API 层、报告渲染**禁止**写状态。
- R4.7 节点必须无全局可变状态、无线程/进程级缓存、无 `print`。

### 4.2 执行骨架（强制顺序）

1. 契约校验（`node_contract` 自动完成）：必填缺失 → `FatalStateError`；待选缺失/格式问题 → 记为 2 级 issue。
2. 读取所需字段，构造只读上下文（禁止把整个 state 丢给 LLM）。
3. 调用 LLM 适配器（如该节点是 LLM 节点）或纯逻辑计算。
4. 计算路由决策（若该节点是条件边的源），写入 `route_*`。
5. 合并条件边副作用（若该分支需要）到**同一个**返回字典。
6. 追加 trace（恰好一条，含 issue 码、写入键、耗时、模型名）。

### 4.3 各节点硬约束

| 节点 | 禁止事项 |
| --- | --- |
| User | 禁止调用 LLM；禁止越权写 1/4 以外的业务字段 |
| Planner | 禁止写 3/6/7/8；禁止在 5 中生成重复 id |
| Teacher | 禁止写 2/3/5/7/8；追加提问必须保留全部既有项 |
| Student | 禁止写 2/4/5/6；禁止清空或截断 `questions` |
| Critic | 禁止写 1/4/9；`2←3` 与 `3=""` 必须与本次更新原子合并；`9` 只读 |
| Target | 禁止写 3/9 与任何业务字段；只输出 `route_target` 与追踪 |
| Output | 禁止写任何业务字段；只允许写 `report_md` 与追踪 |
| Manager | 禁止新增业务字段；清理动作必须与 `m_count` 递增原子合并 |

- R4.8 `Target` 的 `passed` 语义统一实现为 `route_target ∈ {"output","manager"}`，禁止再引入平行布尔字段。
- R4.9 `Output` 的报告由 `runtime/reporting.py` 纯函数渲染（输入：最终 State 快照），节点本身只负责触发与落 `report_md`。

---

## 5. 边（Edge）规范

### 5.1 边表即代码

`graph/edge_table.py` 必须与文档边表一一对应，且是构建图的唯一数据源：

```python
EdgeSpec = NamedTuple("EdgeSpec", [
    ("edge_id", str),          # "critic->teacher"
    ("source", str),
    ("target", str),
    ("kind", Literal["static", "conditional"]),
    ("condition", str),        # 与文档条件文案一致
    ("side_effect", tuple[str, ...]),
    ("breakpoint", bool),
])

EDGE_TABLE: tuple[EdgeSpec, ...] = (...)
```

- R5.1 `builder.py` 必须遍历 `EDGE_TABLE` 装配图；禁止在 builder 里手写零散 `add_edge` 字符串（`START/END` 除外）。
- R5.2 新增/删除边必须同步：`MARS-Prompt.md`、`EDGE_TABLE`、路由函数、路由测试四处。缺一不予合并。
- R5.3 `edge_id` 统一格式 `"<source>-><target>"`，全小写。

### 5.2 路由函数必须纯

```python
def route_critic(state: GraphState) -> Literal["teacher", "target"]:
    return state["route_critic"]
```

- R5.4 路由函数**只读**状态、**只返回**目标名（或 `path_map` 键），禁止：调用 LLM、写状态、抛业务异常、做 IO、读时间/随机数。
- R5.5 路由判定逻辑必须放在**源节点**里完成，并把结果写入 `route_*`；路由函数只做映射。这样“判定 + 副作用”天然处于同一次原子更新中。
- R5.6 禁止在路由函数里重新计算业务条件（否则判定与写入可能不一致，产生不可复现路由）。
- R5.7 每个 `route_*` 必须在节点返回值中出现且只出现一次；禁止依赖“上次残留值”。

### 5.3 条件边副作用的落点

文档中的副作用（Critic 的 `2←3`+置空 3、Manager 的清理）统一实现为：

```python
# Critic 判定不通过分支
if not passed and state["tsc_count"] < TSC_MAX:
    return {
        "working_prompt": state["optimized_prompt"],   # 2 ← 3
        "optimized_prompt": "",                        # 置空 3
        "tsc_count": state["tsc_count"] + 1,           # 10 + 1
        "subtasks": ..., "questions": ..., "heuristic_score": ..., "execution_score": ...,
        "route_critic": "teacher",
        "trace": [trace],
    }
```

- R5.8 副作用**禁止**写在路由函数里，也禁止事后补写；必须与节点更新处于同一返回字典。
- R5.9 冲突顺序固定为「先节点更新、后条件边副作用」；实现上以字典中后者覆盖前者的方式表达，并在 trace 中记录 `side_effects=[...]`。
- R5.10 Manager 同级多条件命中时，必须按 `User > Planner > Teacher` 选择**唯一一条**边；实现为 ordered `if/elif`，禁止并行返回多个目标。

---

## 6. 循环与计数

```python
TSC_MAX = 5
M_MAX = 3
SUBTASK_DONE_THRESHOLD = 85      # > 85 划去
QUESTION_RESOLVED_THRESHOLD = 60 # > 60 划去
LOW_SCORE_THRESHOLD = 60         # < 60 时 Teacher 优先聚焦低分维度
```

- R6.1 `tsc_count` 仅在 Critic **判定不通过且进入 TSC 回边**时 `+1`；进入 Target 分支不得递增。
- R6.2 Critic 判定顺序固定：先按“是否满足要求”判定，再看 `tsc_count >= TSC_MAX`；超限直接走 Target 并标记“TSC 超限”。
- R6.3 `m_count` 仅在 Manager **实际执行回退**时 `+1`；强制进 Output 不递增，但必须标记“M 超限/未通过验收”。
- R6.4 计数递增必须与本次路由决策、清理动作同字典返回；禁止先写计数再单独写路由。
- R6.5 阈值常量只能定义在 `state/constants.py`，禁止在节点内硬编码 `85`/`60`/`5`/`3`。
- R6.6 计数不得回退（除 Manager 回 User/Planner 时按文档将 TSC 归零，这属于显式清理副作用，必须在 trace 中记录 `reset=["tsc_count"]`）。

---

## 7. 断点与人工改道

文档语义：断点命中时状态冻结在「当前节点更新完成之后、下一节点执行之前」；可继续原路由或强制改道；改道不得跳过目标的必填校验；断点不改变 10/11 计数。

- R7.1 断点实现只能位于 `runtime/breakpoints.py`；节点内禁止出现 `interrupt()` / `update_state()`。
- R7.2 断点粒度为**边**：在源节点完成更新后、目标节点执行前挂起。实现方式：源节点后的 `gate` 步骤读取该次路由键与断点配置，命中则 `interrupt(payload)`。
- R7.3 挂起载荷必须包含：`edge_id`、`state_digest`（业务字段哈希）、`route`、`allowed_reroutes`、`counters={tsc_count,m_count}`。禁止把完整 State 直接推给前端（防止密钥/大对象泄漏）。
- R7.4 恢复只接受三选一：`continue` / `reroute:<node>` / `abort`。未知载荷一律 2 级报错并保持原路由。
- R7.5 `reroute` 前必须对目标节点执行**只读契约校验**（`required` 字段存在且格式合规）。校验失败 → 拒绝改道、记录 2 级错误、按原路由继续。
- R7.6 改道不得递增/重置 `tsc_count`、`m_count`；人工介入只写入 trace（`human_intervention=true`、原路由、新路由、操作者、时间）。
- R7.7 改道目标限制为 `EDGE_TABLE` 中该源节点已声明的候选目标 ∪ `{user, planner, teacher, manager, target}`；**禁止**改道到 `output`（除非 `optimized_prompt` 非空）。
- R7.8 `Command` 仅允许在 `runtime/breakpoints.py` 中使用；其余任何位置出现 `Command` 视为违规。
- R7.9 断点开关、命中记录与恢复必须可审计：一次运行的所有断点事件进入 trace，并可重放。

---

## 8. LLM 与提示词

- R8.1 所有 LLM 调用必须经 `llm/adapter.py`；节点禁止直接 import `openai`/`anthropic`/`langchain_*`。
- R8.2 模型、温度、超时、最大重试、基础 URL 由配置注入（`config/settings.py`），禁止硬编码；密钥只来自环境变量。
- R8.3 提示词必须外置为 `prompts/<node>/v<n>.md`，代码中只允许出现版本常量；禁止把长提示词写进 f-string。
- R8.4 每个 LLM 节点必须声明输出 schema（Pydantic），并走 `llm/structured.py` 的“解析 → 校验 → 有限重试 → 兜底”流程；禁止 `json.loads` 后直接信任。
- R8.5 提示词变更必须升版本号并在 PR 描述中附对比说明；禁止静默修改线上提示词。
- R8.6 传入 LLM 的上下文必须显式裁剪（只给必要字段与截断后的列表），禁止 `str(state)` 整体投喂。
- R8.7 日志中禁止出现完整用户提示词与密钥；如需排查，记录哈希 + 长度。
- R8.8 重试必须幂等：不得因重试重复追加列表项、重复递增计数。

---

## 9. 错误处理

### 9.1 分级（与文档一致）

| 级别 | 触发 | 行为 | 视觉 |
| --- | --- | --- | --- |
| 1 级 | 必填字段缺失/为 `None` | 终止优化，抛出 `FatalStateError`，不写入状态 | 红色 |
| 2 级 | 待选缺失、格式不合规、条件性待选缺失、结论无法生成 | 继续运行，产出最小响应，trace 记录错误码 | 黄色 |

- R9.1 1 级错误必须抛 `FatalStateError`，由 `runtime/runner.py` 统一收敛为失败运行；**禁止**节点内 `try/except: pass`。
- R9.2 2 级错误必须写进 `trace.issues`，并在响应摘要中说明；禁止只 `logger.warning` 而不落 trace。
- R9.3 错误码统一格式 `E<级别>-<短横线大写下划线>`，集中定义于 `state/errors.py`，例：
  `E1-MISSING-OPTIMIZED-PROMPT`、`E2-SCHEMA-SUBTASK`、`E2-CONDITIONAL-MISSING-QUESTION`、`E2-TARGET-UNDECIDABLE`。
- R9.4 `Target` 验收结论无法生成时，必须 2 级报错并默认路由 `manager`。
- R9.5 报错后仍须返回可用字段；禁止因 2 级错误返回空字典而不更新本应更新的字段。
- R9.6 禁止用 `assert` 做业务校验（`-O` 下会失效）；`assert` 只允许用于测试与内部不变量。

---

## 10. 可观测性

- R10.1 `NodeTrace` 必须包含：`node`、`started_at`、`duration_ms`、`model`、`prompt_version`、`issues[]`、`writes[]`、`side_effects[]`、`summary`。
- R10.2 每次节点执行**恰好一条** trace；重试不得产生多条（合并计数）。
- R10.3 实时节点状态图必须由图事件流驱动（节点开始/结束/报错/断点），禁止前端轮询自造状态。
- R10.4 日志必须结构化（JSON），至少含 `run_id`、`thread_id`、`node`、`edge_id`、`level`、`code`。禁止中文自由文本作为唯一信息。
- R10.5 时间与 id 必须通过注入的 `clock` / `idgen` 获取，保证测试可复现。

---

## 11. 测试规范

### 11.1 分层

| 层 | 范围 | 强制用例 |
| --- | --- | --- |
| 单元 | 单节点 | 正常路径、每个必填缺失（1 级）、每个待选缺失（2 级）、格式非法、写入键越界 |
| 路由 | 单路由函数 | 边表每条边至少 1 例；不得因状态顺序不同改变结果 |
| 不变量 | 状态 | 见 11.2，每次 CI 全跑 |
| 图集成 | 全图 | 验收通过路径、TSC 超限、M 超限、Manager 三条回退、断点继续、断点改道 |
| 快照 | trace / 最终 State | 固定 seed + mock LLM 后全量快照比对 |

### 11.2 必须存在的不变量测试

1. `performance_criteria` 在初始化后不被任何节点写入。
2. `tsc_count` / `m_count` 单调不减，且只在规定分支递增。
3. 每次 `Critic` 回 Teacher 后：`working_prompt == 旧 optimized_prompt` 且 `optimized_prompt == ""`。
4. `subtasks` / `questions` 只增不减；`dropped` 项保留。
5. 任何节点返回值键集合 ⊆ `writes ∪ {"trace"}`。
6. 状态 JSON 往返无损（`json.loads(json.dumps(state)) == state`）。
7. 断点恢复前后业务字段与计数器完全一致（除人工改道导致的业务流转）。
8. 重试不产生重复列表项与重复计数。

- R11.1 测试中 LLM 必须打桩（fixture 回放），禁止真实网络调用；CI 断网必须全绿。
- R11.2 覆盖率门槛：`graph/state`、`graph/routing` ≥ 95%，`graph/nodes` ≥ 85%，整体 ≥ 85%。
- R11.3 每个 bug 修复必须附回归用例；无复现用例的修复不予合并。
- R11.4 测试数据放 `tests/fixtures/`，禁止在测试函数内堆 50 行内联状态。

---

## 12. 代码风格

- R12.1 `ruff` 全绿（`E,F,I,N,UP,B,SIM,RUF`），`mypy --strict` 全绿。禁止 `# type: ignore` 无错误码；禁止 `# noqa` 无原因。
- R12.2 禁止可变默认参数（`def f(x=[])`）；禁止在模块级创建可变单例。
- R12.3 异常必须自定义且继承自 `MarsError`；禁止裸 `raise Exception`、禁止 `except Exception` 后静默。
- R12.4 公共函数/类必须有 docstring，且节点 docstring 固定含 `接收 / 更新 / 报错` 三段。
- R12.5 注释只解释“为什么”，不解释“做了什么”；禁止保留被注释掉的代码。
- R12.6 单个函数 ≤ 60 行，圈复杂度 ≤ 12；节点内部若超限，必须抽出纯函数到 `state/**` 或节点私有 helper。
- R12.7 禁止 `from x import *`；禁止相对导入跨层（`api` 内可用相对导入）。
- R12.8 字符串错误/日志一律英文常量 + 可选中文 message 字段；禁止把用户可见文案散落在节点里（统一 `messages.py`）。

---

## 13. 提交与评审

- R13.1 提交信息：`<type>(<scope>): <summary>`，`type ∈ feat|fix|refactor|test|docs|chore`，`scope ∈ state|node|edge|runtime|llm|api`。
- R13.2 涉及以下任一变更必须单独 PR 并在描述中列出影响面：State 字段、边表、循环计数、断点语义、提示词版本。
- R13.3 偏离本规范必须走 ADR（`docs/adr/NNNN-*.md`），说明动机、替代方案、回滚方式；**未记录的偏离视为违规**。
- R13.4 PR 自检（缺一不予评审）：
  - [ ] 字段映射表未新增未登记键
  - [ ] 边表与 `MARS-Prompt.md` 一致
  - [ ] 节点 `required/optional/writes` 与文档一致
  - [ ] 不变量测试通过
  - [ ] 断点路径手工验证（继续 + 改道 + 拒绝改道）
  - [ ] 无密钥、无真实提示词进入日志

---

## 14. 禁止清单（零容忍）

| # | 反模式 | 原因 |
| --- | --- | --- |
| 1 | 节点原地 `state["subtasks"].append(...)` | 破坏原子更新与快照 |
| 2 | 在条件边函数里改状态 | LangGraph 路由必须纯，且违反文档原子性 |
| 3 | 一个节点多次写状态 / 多次 `update_state` | 违反“一次更新” |
| 4 | 用编号字符串 `"3"` 作状态键 | 可读性与可维护性灾难 |
| 5 | 节点直接 `import openai` 并读环境变量 | 绕过适配器与配置治理 |
| 6 | 把整个 State 序列化进 prompt | 上下文污染、成本与泄漏风险 |
| 7 | 1 级错误 `try/except` 吞掉 | 静默失败，无法定位 |
| 8 | 删除 `dropped` 的子任务/提问 | 违反审计与 append-only |
| 9 | 断点恢复时重算并改动计数器 | 破坏“断点不改变计数” |
| 10 | 在 `builder.py` 写业务判断 | 图装配与业务耦合 |
| 11 | 硬编码阈值 `85/60/5/3` | 与文档失同步 |
| 12 | `print` / 未结构化日志 | 不可观测 |
| 13 | 非确定性输出（未注入时钟/随机/seed） | 不可复现 |
| 14 | State 中存放不可序列化对象 | checkpointer 崩溃 |

---

## 15. 节点完成定义（DoD）

新增或修改任一节点，必须同时满足：

1. 契约装饰器参数与 `MARS-Prompt.md` 节点章节完全一致。
2. 返回值键 ⊆ 声明写集，且包含唯一 trace。
3. 1 级 / 2 级错误路径均有测试。
4. 路由键与副作用（如有）在同一次返回中。
5. 不变量测试全绿，覆盖率达标。
6. 节点 docstring 的 `接收 / 更新 / 报错` 与文档一致。
7. 无新增未登记字段、无硬编码阈值、无越层 import。

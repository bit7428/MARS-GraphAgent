# 架构说明（实现视角）

> 本文解释代码如何落地 `MARS-Prompt.md`，不重新定义业务语义。
> 字段含义、节点职责、边表与循环规则以核心文档为准；若本文与核心文档冲突，以核心文档为准。

## 1. 分层与依赖

```
api → runtime → graph → state
                 ↓
                llm → prompts
```

| 层 | 目录 | 职责 | 禁止 |
| --- | --- | --- | --- |
| API | `mars/api/` | DTO 校验、SSE、静态托管、异常映射 | 业务判断、直接改 State |
| Runtime | `mars/runtime/` | 运行生命周期、断点、检查点、落盘、报告 | 节点业务逻辑 |
| Graph | `mars/graph/` | State、节点、路由、边表、图装配 | 访问 API、读写文件 |
| LLM | `mars/llm/` | 适配器、结构化输出、推荐模板 | 感知节点名与业务字段 |
| Config | `mars/config/` | 环境变量、节点配置、密钥存储 | 把密钥写入 State / 日志 |

- `graph/state/` 是纯数据与纯校验层，不 import LangGraph 或 LLM SDK。
- 节点之间禁止互相 import；共享逻辑放在 `state/` 或节点私有 helper。
- `builder.py` 只做 `add_node` / `add_edge` / `add_conditional_edges`，不写业务条件。

## 2. State 字段映射

State 为 `TypedDict`，只保存 JSON 可序列化数据。

| # | 代码名 | 类型 | 业务写者 | 合并方式 |
| --- | --- | --- | --- | --- |
| 1 | `initial_prompt` | `str` | User | replace |
| 2 | `working_prompt` | `str` | Planner、Critic（TSC 快照） | replace |
| 3 | `optimized_prompt` | `str` | Student、Critic（置空） | replace |
| 4 | `optimization_goal` | `str` | User | replace |
| 5 | `subtasks` | `list[Subtask]` | Planner、Critic | 整表替换，append-only 语义 |
| 6 | `questions` | `list[Question]` | Teacher、Critic | 整表替换，append-only 语义 |
| 7 | `heuristic_score` | `ScoreDetail \| None` | Critic | replace |
| 8 | `execution_score` | `ScoreDetail \| None` | Critic | replace |
| 9 | `performance_criteria` | `list[PerformanceCriterion]` | 仅入口 | 初始化后只读 |
| 10 | `tsc_count` | `int` | Critic | replace |
| 11 | `m_count` | `int` | Manager | replace |

非业务通道：

| 通道 | 键 | 写者 | 说明 |
| --- | --- | --- | --- |
| 路由 | `route_critic` / `route_target` / `route_manager` | 对应源节点 | 只供条件边读取 |
| 追踪 | `trace` | 所有节点 | `Annotated[list[NodeTrace], operator.add]`，每次恰好一条 |
| 产物 | `report_md` | Output | 不参与业务校验与节点读取 |

元素结构：

```text
Subtask  = {id, content, source, status: pending|done|dropped, score}
Question = {id, content, target_task_id, status: open|resolved|dropped, score}
ScoreDetail = {score: 0..100, dimensions: dict[str, int], summary, evidence: list[str]}
Criterion   = {name, threshold: number, comparator: gte|lte|eq}
```

- `subtasks` / `questions` 只增不减：划去只改 `status`，保留记录。
- id 由 `state/ids.py` 生成，不直接使用随机 UUID，保证快照可复现。

## 3. 节点契约

每个节点通过 `@node_contract` 声明必填、条件待选、写入集合与路由键；
越界写入、原地修改 State、缺少 trace 都会抛 `CodingContractError`。

| 节点 | 必填（1 级） | 条件待选（2 级） | 写入 |
| --- | --- | --- | --- |
| User | 无 | 1/4（Manager 唤醒且缺失/空白） | 1、4 |
| Planner | 1、4 | 3、5（TSC 进行中） | 2、5 |
| Teacher | 2、5 | 1/4（Manager 唤醒）；3/6/7/8（TSC 进行中） | 6 |
| Student | 2、4、6 | 5（无条件） | 3 |
| Critic | 3、4、5、6 | 2/7/8（TSC 第二轮起） | 5、6、7、8、10；副作用 2←3、3 置空 |
| Target | 3、9、10、11 | 无 | 无（只写 `route_target`） |
| Output | 3 | 无 | `report_md` |
| Manager | 2、3、5、6、7、8、9、10、11 | 无 | 11；副作用清理 2/3/5/6/7/8、TSC 归零 |

### 为什么待选字段要“有条件”

早期实现把所有待选字段的缺失都报 2 级，导致一次健康运行出现十余条误报：
Planner 首轮必然没有 3/5，Teacher 首轮必然没有 6/7/8，Critic 首轮必然没有 7/8。
现在按节点前提收口：

| 触发条件 | 判定 | 适用 |
| --- | --- | --- |
| `manager` | `m_count > 0` | User / Teacher 的 1、4 |
| `tsc` | `tsc_count > 0` | Planner、Teacher、Critic 的循环产物 |
| 无条件 | 始终检查 | Student 的 5 |

M 回退会重置 `tsc_count` 并清空上游产物（User/Planner 回退），这是文档定义的**正常复位**，
因此不把复位后的缺失判为异常；只有 TSC 仍在进行时才代表“本轮应该存在的产物丢了”。

### 置空与格式校验

- Critic 进入 TSC 前把 `optimized_prompt` 置空；Manager 回 User/Planner 时清空 2/3。
- 当 `tsc_count > 0` 或 `m_count > 0` 时，2/3 的空串属于正常编辑槽位，不判
  `E2-SCHEMA-WORKING-PROMPT` / `E2-SCHEMA-OPTIMIZED-PROMPT`。
- 其他字段仍按核心文档的格式标准严格校验。

## 4. 边表（12 条）

| 边 | 类型 | 条件 | 副作用 |
| --- | --- | --- | --- |
| `user->planner` | 普通 | 无 | 无 |
| `planner->teacher` | 普通 | 无 | 无 |
| `teacher->student` | 普通 | 无 | 无 |
| `student->critic` | 普通 | 无 | 无 |
| `critic->teacher` | 条件 | 不满足且 `tsc_count < TSC_MAX` | 2←3、3 置空、10+1 |
| `critic->target` | 条件 | 满足要求或 `tsc_count >= TSC_MAX` | 无 |
| `target->output` | 条件 | 验收通过 | 无 |
| `target->manager` | 条件 | 验收不通过 | 无 |
| `manager->user` | 条件 | 目标/输入缺陷 | 清空 2/3/5/6/7/8、TSC 归零、11+1 |
| `manager->planner` | 条件 | 子任务缺陷 | 清空 3/6/7/8、TSC 归零、11+1 |
| `manager->teacher` | 条件 | 引导缺陷 | 2←3、3 置空、11+1 |
| `manager->output` | 条件 | `m_count >= M_MAX` | 11 不递增，标记失败 |

实现要点：

- `edge_table.py` 是唯一数据源；`builder.py` 遍历它装配图，并为每条边插入 `gate__*` 节点。
- 条件边的路由函数是**纯函数**：只读 `route_*`，不写状态、不调 LLM。
- 副作用在源节点里与路由键同一次返回，保证一次原子更新；不在路由函数中补写。
- Manager 同级多条件命中时按 `User > Planner > Teacher` 选择唯一一条边。

## 5. 循环与阈值

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `TSC_MAX` | 5 | TSC 循环上限，运行时可覆盖 |
| `M_MAX` | 3 | M 回退上限，运行时可覆盖 |
| `SUBTASK_DONE_THRESHOLD` | 85 | 子任务分数 **> 85** 视为完成 |
| `QUESTION_RESOLVED_THRESHOLD` | 60 | 提问分数 **> 60** 视为已解决 |
| `LOW_SCORE_THRESHOLD` | 60 | 7/8 低于 60 时优先聚焦低分维度 |

- `tsc_count` 只在 Critic 判定不通过且进入回边时 +1；进入 Target 不递增。
- `m_count` 只在 Manager 实际回退时 +1；强制进 Output 不递增。
- 计数与清理动作必须在同一次返回中完成，不得拆成多次写入。

## 6. 断点与人工改道

- 命中边断点时，状态冻结在“源节点更新完成、目标节点执行前”。
- 挂起载荷只包含：`edge_id`、`state_digest`、`route`、`allowed_reroutes`、`counters`；
  不把完整 State 推给前端。
- 恢复动作：`continue` / `reroute:<node>` / `abort`；未知载荷按 2 级错误处理并保持原路由。
- 改道前对目标节点做只读契约校验；不满足必填字段则拒绝改道并按原路由继续。
- 改道不改变 TSC / M 计数，只写 trace 的人工介入记录。
- `Command` 仅允许出现在 `runtime/breakpoints.py`。

## 7. 运行与持久化

- `RunManager` 在进程内维护运行记录与事件队列，通过 SSE 推送给前端。
- `RunArtifactStore` 把 `meta.json`、`run.log`、`state.json`、`report.md`、
  `output_prompt.txt`、`error.json` 写入 `data/runs/<run_id>/`。
- `run.log` 写入前剔除完整提示词与报告正文；`state.json` 含业务内容，按敏感数据管理。
- 图检查点仍是 `InMemorySaver`：重启后不能续跑，但已完成运行的报告与日志可继续查看。

## 8. 不变量（测试强制）

1. `performance_criteria` 初始化后不被任何节点写入。
2. 每次节点执行恰好追加一条 trace。
3. 节点返回值键集合 ⊆ `writes ∪ side_effect_writes ∪ {route_key, trace}`。
4. 节点不原地修改传入 State（深拷贝比对）。
5. `tsc_count` / `m_count` 单调不减，且只在规定分支递增。
6. Critic 回 Teacher 后：`working_prompt == 旧 optimized_prompt` 且 `optimized_prompt == ""`。
7. `subtasks` / `questions` 只增不减，`dropped` 项保留。
8. 正常路径、TSC 超限路径、Manager 回退路径的 trace 均无 issues。
9. State 经 JSON 往返无损。

## 9. 代码定位

| 关注点 | 文件 |
| --- | --- |
| State 定义 | `mars/graph/state/schema.py` |
| 字段常量与阈值 | `mars/graph/state/constants.py` |
| 分级校验 | `mars/graph/state/validate.py` |
| 错误码 | `mars/graph/state/errors.py` |
| 节点契约与 trace | `mars/graph/contract.py` |
| 边表 | `mars/graph/edge_table.py` |
| 图装配 | `mars/graph/builder.py` |
| 路由 | `mars/graph/routing/` |
| 断点 | `mars/runtime/breakpoints.py` |
| 运行管理 | `mars/runtime/runner.py` |
| 落盘 | `mars/runtime/persistence.py` |
| 报告渲染 | `mars/runtime/reporting.py` |
| API | `mars/api/app.py` |

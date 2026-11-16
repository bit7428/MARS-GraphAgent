# MARS-Graph

多智能体协作提示词优化平台。基于 LangGraph，围绕 State / Node / Edge 三个概念实现
「User → Planner → Teacher → Student → Critic → Target」的提示词优化闭环，并支持
Target 验收失败后的 Manager 回退管控、边级断点与人工改道。

## 能力边界

本仓库严格实现 `MARS-Prompt.md` 与 `CODE_STANDARDS.md` 已定义的能力：

- 8 个业务节点：User、Planner、Teacher、Student、Critic、Target、Output、Manager。
- 边表、条件路由、TSC / M 双循环计数与上限、状态分级校验。
- 6 个 LLM 节点（Planner / Teacher / Student / Critic / Target / Manager）经统一适配器调用。
- 边级断点：命中后冻结状态，可继续原路由、人工改道或中止。
- FastAPI 接口：创建运行、状态快照、事件流、断点配置、恢复运行、节点模型配置。
- Output 报告由纯函数渲染，最终输出 `optimized_prompt`。
- 每次优化在 `data/runs/<run_id>/` 持久化报告、日志、状态快照与元信息；前端可查看、下载并删除。

明确不做（文档未定义）：

- 不做登录、多租户与权限体系；前端只消费既有接口，不引入账号概念。
- 不做数据库与多进程持久化；图检查点仍在进程内存，服务重启后不能续跑，但已完成运行的报告与日志仍可查看。
- 不做用户体系、鉴权、计费；API Key 只从环境变量读取，不进入状态与接口返回。
- 不扩展文档之外的 State 字段、节点、边或循环语义。

## 数据目录

每次优化创建一个子文件夹：

```
data/runs/<run_id>/
  meta.json            # 名称、状态、验收结论、循环上限与计数
  run.log              # 结构化事件日志（不记录完整提示词与报告）
  state.json           # 最近一次状态快照
  report.md            # Output 生成的总结报告
  output_prompt.txt    # 最终提示词
  error.json           # 仅失败运行生成
```

数据目录可通过 `MARS_DATA_DIR` 修改；默认 `data/runs`，已加入 `.gitignore`。删除操作只允许在运行结束（completed / failed）后执行。


## 快速开始

```bash
uv sync
uv run pytest
uv run uvicorn mars.api.app:app --reload
```

环境变量（前缀 `MARS_`）：

| 变量 | 说明 |
| --- | --- |
| `MARS_API_KEY_ENV` | 存放 LLM Key 的环境变量名，默认 `MARS_LLM_API_KEY` |
| `MARS_DEFAULT_MODEL` | 默认模型名 |
| `MARS_BASE_URL` | OpenAI 兼容接口地址 |
| `MARS_NODE_CONFIGS` | 节点配置覆盖，JSON 字符串 |
| `MARS_DATA_DIR` | 运行产物目录，默认 `data/runs` |

示例：

```bash
export MARS_LLM_API_KEY=sk-xxx
export MARS_BASE_URL=https://api.deepseek.com/v1
export MARS_DEFAULT_MODEL=deepseek-chat
```

## 提示词版本

每个 LLM 节点的提示词位于 `mars/prompts/<node>/v1.md`，通过节点配置接口选择版本。
输出结构由代码中的 Pydantic schema 强校验，格式不符会触发有限重试。

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/meta` | 演示模式与默认循环上限 |
| `GET` | `/graph/edges` | 边表，用于配置断点 |
| `POST` | `/runs` | 创建运行（可带 `name`、`tsc_max`、`m_max`、`breakpoints`） |
| `GET` | `/runs` | 运行摘要列表（内存 + 持久化合并） |
| `GET` | `/runs/{id}` | 状态快照；内存缺失时回退磁盘快照 |
| `GET` | `/runs/{id}/events` | SSE 事件流 |
| `GET` | `/runs/{id}/report` | 读取磁盘报告与最终提示词 |
| `GET` | `/runs/{id}/log` | 读取运行日志末尾 |
| `DELETE` | `/runs/{id}/data` | 删除该优化的整个数据子文件夹 |
| `POST` | `/runs/{id}/breakpoints` | 替换断点边集合 |
| `POST` | `/runs/{id}/resume` | 继续 / 改道 / 中止，可附用户补充 |
| `GET` | `/config/nodes` | 查看 6 个 LLM 节点配置与可用模板版本 |
| `PATCH` | `/config/nodes/{node}` | 修改模型、温度、超时、提示词版本 |
| `DELETE` | `/config/nodes/{node}` | 恢复节点默认配置 |

恢复载荷：

```json
{"action": "continue"}
{"action": "reroute", "target": "planner", "operator": "alice"}
{"action": "abort"}
```

在 Manager→User 断点恢复时，可附带 `initial_prompt` / `optimization_goal` 与
`supplement_mode`（`append` 或 `replace`），作为 User 节点的追加输入。

## 前端控制台

`frontend/` 是配套的开发者工作台：运行控制台（实时节点状态图 / 断点干预 / 状态抽屉）、
新建任务、LLM 节点配置、输出报告、历史运行（含持久化数据查看与删除）。技术栈为
React 18 + TypeScript + Vite，节点图用手写 SVG 渲染，构建产物由 FastAPI 直接托管。

```bash
# 一次性：安装依赖并构建
cd frontend
npm install
npm run build

# 单进程启动（API + 静态页面）：http://127.0.0.1:8000
cd ..
MARS_DEMO=1 uv run uvicorn mars.api.app:app --host 127.0.0.1 --port 8000
```

开发模式（前端热更新，接口经 Vite 代理到 8000）：

```bash
uv run uvicorn mars.api.app:app --reload          # 终端 1
cd frontend && npm run dev                        # 终端 2 → http://127.0.0.1:5173
```

演示模式（免 API Key，用内置确定性样例模型跑完整流程）：

| 变量 | 说明 |
| --- | --- |
| `MARS_DEMO=1` | 启用 `DemoAdapter`，无需任何密钥 |
| `MARS_DEMO_DELAY` | 每个事件的人工延迟秒数，默认 0.35，便于观察状态图 |
| `MARS_DEMO_PROFILE=fail` | Target 永不通过，用于演示 M 超限的失败报告 |

界面截图见 `docs/screenshots/`。真实模型仍需为 `mars/prompts/<node>/v1.md` 填入系统提示词。

## 质量门槛

```bash
uv run ruff check mars
uv run ruff format --check mars
uv run mypy mars
uv run pytest --cov=mars
```

覆盖：`graph/state` 与 `graph/routing` 100%，`graph/nodes` ≥ 97%，整体 93%。

## 文档

- `MARS-Prompt.md`：产品与图语义唯一权威。
- `CODE_STANDARDS.md`：实现规范。

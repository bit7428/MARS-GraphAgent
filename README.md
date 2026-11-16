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

明确不做（文档未定义）：

- 不做前端页面；实时状态图由 SSE 事件流供外部消费。
- 不做数据库与多进程持久化；检查点保存在进程内存，重启即丢失。
- 不做用户体系、鉴权、计费；API Key 只从环境变量读取，不进入状态与接口返回。
- 不扩展文档之外的 State 字段、节点、边或循环语义。

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

示例：

```bash
export MARS_LLM_API_KEY=sk-xxx
export MARS_BASE_URL=https://api.deepseek.com/v1
export MARS_DEFAULT_MODEL=deepseek-chat
```

## 提示词占位

按当前交付要求，`mars/prompts/<node>/v1.md` 全部为空文件。接入真实模型前需要为
Planner / Teacher / Student / Critic / Target / Manager 填入系统提示词，至少说明各自的
JSON 输出字段；输出结构由代码中的 Pydantic schema 强校验，格式不符会触发有限重试。

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/graph/edges` | 边表，用于配置断点 |
| `POST` | `/runs` | 创建运行 |
| `GET` | `/runs/{id}` | 状态快照、下一节点、断点载荷 |
| `GET` | `/runs/{id}/events` | SSE 事件流 |
| `POST` | `/runs/{id}/breakpoints` | 替换断点边集合 |
| `POST` | `/runs/{id}/resume` | 继续 / 改道 / 中止，可附用户补充 |
| `GET` | `/config/nodes` | 查看 6 个 LLM 节点配置 |
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

## 质量门槛

```bash
uv run ruff check mars
uv run ruff format --check mars
uv run mypy mars
uv run pytest --cov=mars
```

覆盖：`graph/state` 与 `graph/routing` 100%，`graph/nodes` ≥ 97%，整体 96%。

## 文档

- `MARS-Prompt.md`：产品与图语义唯一权威。
- `CODE_STANDARDS.md`：实现规范。

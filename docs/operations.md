# 运维与隐私手册

> 适用于当前的单实例、内网部署形态。涉及多租户、水平扩展或公网暴露时，请先阅读
> 文末「已知限制」，不要在未加固的情况下直接上线。

## 1. 启动与停止

```bash
# 安装依赖
uv sync

# 构建前端（可选；不构建时只提供 API）
cd frontend && npm install && npm run build && cd ..

# 启动
uv run uvicorn mars.api.app:app --host 127.0.0.1 --port 8000
```

- **必须单 worker。** 运行记录、事件队列、图检查点与节点配置覆盖都在进程内存，
  `--workers N` 会让请求落到不同进程，表现为随机 404、状态丢失或 SSE 断流。
- 健康检查：`GET /health`。该接口只表示进程存活，不检查模型连通性；
  模型连通性请用 `POST /config/nodes/{node}/test`。
- 停止服务会中断正在运行的图；已完成运行的报告/日志已落盘，可在重启后从历史页查看。
- 前端由 FastAPI 托管 `frontend/dist`；修改前端后必须重新 `npm run build`。

## 2. 配置

所有配置通过 `MARS_` 前缀环境变量注入：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MARS_LLM_API_KEY` | 空 | 默认密钥；也可通过前端写入本地文件 |
| `MARS_API_KEY_ENV` | `MARS_LLM_API_KEY` | 节点默认引用的密钥变量名 |
| `MARS_DEFAULT_MODEL` | `deepseek-chat` | 默认模型 |
| `MARS_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容接口 |
| `MARS_TEMPERATURE` | `0.2` | 默认温度 |
| `MARS_TIMEOUT_S` | `60` | 单次调用超时（秒） |
| `MARS_MAX_RETRIES` | `2` | 结构化输出重试次数 |
| `MARS_PROMPT_VERSION` | `v1` | 默认提示词版本 |
| `MARS_NODE_CONFIGS` | 空 | 节点级覆盖（JSON 字符串） |
| `MARS_DATA_DIR` | `data/runs` | 运行产物目录 |
| `MARS_HOME` | 当前工作目录 | 本地密钥根目录 |

生产环境建议用系统级环境变量或密钥管理服务注入，不要提交 `.env`。

## 3. 密钥

| 项 | 说明 |
| --- | --- |
| 默认路径 | `<MARS_HOME 或工作目录>/.mars/secrets.json` |
| 写入方式 | 前端「节点配置 → 设置密钥」，或 `PUT /config/secrets/{env_name}` |
| 读取 | 启动时加载；`os.environ.setdefault`，显式环境变量优先 |
| 响应 | 只返回 `configured` / `tail` / `source`，明文永不回传 |
| 日志 | 不记录密钥；错误信息只包含环境变量名 |
| 清除 | 前端或 `DELETE /config/secrets/{env_name}`，同时删除进程变量与文件记录 |

注意：

- `.mars/` 已加入 `.gitignore`，但**不要**把密钥写进 README、测试、截图或工单。
- 截图前先确认页面没有显示密钥、绝对路径或真实提示词。
- 如果密钥曾经出现在聊天记录、日志、截图或公开仓库中，**立即在供应商侧轮换**，
  仅删除文件并不能使已泄露的密钥失效。
- 不同供应商可配置不同 `api_key_env`，但前端的“未配置”拦截按节点引用逐个判断。

## 4. 数据与保留

```
data/runs/<run_id>/
  meta.json            # 元信息，不含完整提示词
  run.log              # 逐行 JSON 事件，已剔除提示词/报告正文
  state.json           # 状态快照（含业务内容）
  report.md            # 报告
  output_prompt.txt    # 最终提示词
  error.json           # 失败运行的错误详情
```

- `data/runs/*` 已加入 `.gitignore`；`data/runs/.gitkeep` 用于保留目录。
- 运行中/暂停中的记录禁止删除；结束后可通过 `DELETE /runs/{id}/data` 删除整个子目录。
- 当前没有自动保留策略与备份。请用文件系统快照/备份工具管理 `data/runs`，
  或定期清理过期目录；删除前确认没有正在运行的任务。
- `state.json`、`report.md`、`output_prompt.txt` 可能包含用户原始提示词与业务信息，
  属于敏感数据，应按数据分级要求访问与备份。

## 5. 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 启动后所有页面 404 / 历史为空 | 多 worker 启动 | 改为单 worker |
| 创建任务后立即失败，提示缺少密钥 | 节点引用的 `api_key_env` 未配置 | 在节点配置中设置密钥，或导出对应环境变量 |
| `E1-MISSING-*` 终止 | 必填状态缺失（如 Critic 未产出 7/8） | 检查 LLM 是否可用、提示词是否符合 JSON 契约 |
| `E2-LLM-SCHEMA` | 模型输出不合约 | 检查提示词版本与节点 schema；必要时调低温度 |
| 断点继续后无进展 | 恢复载荷非法或目标契约不满足 | 查看 `gate:*` trace 的 issues 与 `allowed_reroutes` |
| SSE 不更新 | 反向代理缓冲 / 连接中断 | 关闭代理缓冲，确认 `text/event-stream` 直通 |
| 报告页打不开 | 运行仍在进行，或数据目录被清理 | 等待结束或检查 `data/runs/<id>/report.md` |

## 6. 发布前隐私检查清单

在推送仓库或交付镜像前逐项确认：

```bash
# 1. 查看未跟踪与被忽略的本地文件，确认没有密钥/运行数据
git status --short
git status --ignored --short

# 2. 扫描疑似密钥（按需扩展）
git grep -nE 'sk-[A-Za-z0-9_-]{16,}|github_pat_|gh[pousr]_|Bearer ' -- . ':!uv.lock'

# 3. 检查提交作者信息是否包含个人邮箱
git log --format='%an <%ae>' | sort -u

# 4. 确认以下本地目录不会被提交
#    .mars/           本地密钥
#    data/runs/*      运行数据（保留 .gitkeep）
#    .playwright-mcp/ 浏览器调试快照
#    .env             本地环境变量
```

- 发布前删除 `.mars/secrets.json`、`data/runs/*`、`.playwright-mcp/` 与本机 `.env`；
  它们可能包含密钥、真实提示词、页面快照或绝对路径。
- 如果截图包含本机绝对路径，先打码或重新截图。
- 如果确实需要保留历史提交，使用仓库级的 `user.name` / `user.email` 覆盖；
  如果历史提交已经包含个人邮箱，可在推送前用 `git filter-branch` 改写为
  GitHub noreply 地址（改写会改变提交哈希，强制推送前务必确认没有协作者依赖旧历史）。

## 7. 升级与回滚

- 提示词按 `vN.md` 版本化：新增版本不会影响正在使用的版本；删除版本时至少保留一个，
  且不能删除当前节点引用的版本。
- 节点配置覆盖只存在于进程内存，重启后回到环境变量默认值；
  如需稳定配置，请写入 `MARS_NODE_CONFIGS`。
- 升级前先跑：

```bash
uv run ruff check mars
uv run ruff format --check mars
uv run mypy mars
uv run pytest --cov=mars
cd frontend && npm run build
```

## 8. 已知限制

- 无登录、权限、租户隔离与计费；不要直接暴露公网。
- 图检查点不持久化，重启不能续跑；运行报告/日志可以查看。
- 无并发上限、运行超时/费用预算、取消接口与事件 TTL。
- 无数据库、备份、指标与分布式追踪；SSE 依赖单进程内存队列。
- 无前端单元测试与浏览器 E2E；截图是开发期记录。
- API 未版本化，升级可能包含破坏性变更。

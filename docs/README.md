# 文档导航

本目录存放**实现视角**的说明与设计记录。产品与图语义的唯一权威是仓库根目录的
[`MARS-Prompt.md`](../MARS-Prompt.md)；实现规范是 [`CODE_STANDARDS.md`](../CODE_STANDARDS.md)。
两者与本文档冲突时，以核心文档为准。

## 阅读顺序

| 顺序 | 文档 | 读者 | 内容 |
| --- | --- | --- | --- |
| 1 | [`../README.md`](../README.md) | 所有人 | 项目定位、能力、快速开始、配置、API 与边界 |
| 2 | [`../MARS-Prompt.md`](../MARS-Prompt.md) | 产品 / 研发 | State 字段、8 个节点、12 条边、TSC/M 循环、断点语义 |
| 3 | [`../CODE_STANDARDS.md`](../CODE_STANDARDS.md) | 研发 | 分层、命名、节点/边契约、测试与提交规范 |
| 4 | [`architecture.md`](architecture.md) | 研发 | 字段映射、节点输入输出、条件校验前提、不变量 |
| 5 | [`operations.md`](operations.md) | 运维 / 部署 | 启动模式、密钥、数据保留、隐私清理、排障 |
| 6 | [`design/frontend-design-v0.1.md`](design/frontend-design-v0.1.md) | 前端 / 产品 | 页面结构、交互细节与实现变更记录 |

## 文档状态

- `README.md`、`architecture.md`、`operations.md` 与当前代码同步维护。
- `design/frontend-design-v0.1.md` 是**设计过程记录**：其中“演示模式（DemoAdapter / MARS_DEMO）”
  相关描述已在 v0.3 移除，保留用于解释当时的设计取舍。
- `screenshots/` 下的截图是开发期记录。部分截图仍显示 `demo` 模型或演示入口，
  不代表当前版本能力；当前版本必须配置真实模型与密钥才能运行。

## 维护约定

1. 修改 State 字段、边表、循环计数或断点语义时，必须同步更新：
   `MARS-Prompt.md` → `docs/architecture.md` → 代码与测试。
2. 修改部署方式、环境变量或数据目录时，必须同步更新 `README.md` 与 `operations.md`。
3. 新增截图前先检查是否包含密钥、绝对路径、真实提示词或个人信息；
   推荐在关闭真实数据的独立环境中截图。

# Spec 001：Self-Host 学习平台基础壳

状态：待评审草案；确认后才能开始实现
日期：2026-07-10
适用阶段：Platform Stage 1

## 1. 评审结论摘要

本规格定义从“已有 framework 与 academic 原型”走向“可 self-host 的学习平台”的第一段实现。Stage 1 的交付不是资料导入、RAG 问答或 chat 应用，而是一个可运行、可观察、可迁移、可扩展的平台基础壳。

评审时应重点确认五件事：产品边界是否清晰、Postgres 是否从第一天起作为事实来源、workspace 是否足以成为后续数据归属根、Web 首屏是否是工作台、以及本阶段是否严格不提前实现 ingestion/agent chat。

## 2. 背景

正确仓库已经拥有三类资产：

- `hello_agents/`：可复用的 agent framework，含工具、上下文、memory、RAG、MCP 和 streaming 等能力。
- `academic_companion/`：学习/研究领域原型，以及非最终入口的 API/Web 原型。
- 内置 CS、八股和 LeetCode 数据：测试、演示和未来迁移样本，不主导产品数据模型。

当前缺口不是再添加 agent，而是补足产品运行系统：产品 API/Web、workspace、权威数据库、可复现部署、运行状态与后续资料生命周期的承载边界。

Stage 0R 已确认：产品是学习平台而非 chat-first 双模式应用；`hello_agents`/`academic_companion`/product app 分层；Postgres 为产品事实来源，Qdrant 可重建，Redis 非权威；误仓库代码仅作参考。

## 3. 目标

建立最小 self-host 平台，使单用户能够通过 Web 创建并选择 workspace，并看到平台的运行状态。完成后，项目不再只是 Python package/demo，而是拥有可启动产品入口和持久化业务根。

## 4. 成功标准

Stage 1 完成时，必须同时满足：

- `docker compose up --build` 能启动 Postgres、Qdrant、Redis、API 和 Web。
- Postgres migration 能在干净数据库中创建 `workspaces` 表。
- API 提供存活检查、就绪检查、非敏感系统信息及最小 workspace CRUD。
- Web 首页是 workspace 工作台：展示系统状态、workspace 列表和创建入口，而不是 chat 页面。
- 新建 workspace 经 Postgres 持久化，重启 API 后仍可读取。
- Qdrant、Redis、storage root 的可用或降级状态可见，但不暴露连接 URL、密钥或原始异常。
- `apps/api` 测试、Web lint/build、Compose 配置检查和实际启动验证均有明确命令与记录。
- 实质性代码变更已按 `AGENTS.md` 留下 OCR/review 记录；若不执行 OCR，须记录原因。

## 5. 约束与不变量

- 产品业务代码只能进入 `apps/`；不得把 workspace、HTTP 路由、产品状态或产品持久化写入 `hello_agents/` 或 `academic_companion/`。
- Postgres 是正式 self-host 路线的业务事实来源；Qdrant 只保存可重建的索引；Redis 不保存不可替代的业务事实。
- Stage 1 允许单用户 self-host，不设计登录、多租户或复杂权限。
- 日志不得记录 API key、原始上传内容、完整敏感 agent 输入或数据库连接凭据。
- 产品 API 从 `/api/v1` 起建立自己的合约；原型 `/api/*` 不构成兼容性承诺。
- 首屏必须是工作台，而不是 marketing landing page，也不是 chat-first 页面。

## 6. 范围内

### 6.1 仓库与依赖边界

新增下列结构：

```text
apps/
  api/
    learn_platform_api/
    alembic/
    tests/
    requirements.txt
    Dockerfile
  web/
    src/
    package.json
    package-lock.json
    Dockerfile
docker-compose.yml
storage/
```

根 `pyproject.toml` 继续描述 framework。产品 API 依赖放在 `apps/api/requirements.txt`，产品 Web 依赖放在 `apps/web/package.json`。根 `uv.lock` 漂移修复是独立的 framework 依赖工作，不在本 Stage 偷渡处理。

### 6.2 最小产品 API

| 方法 | 路径 | 用途与约束 |
|---|---|---|
| `GET` | `/health` | 进程存活检查；不得访问外部依赖 |
| `GET` | `/ready` | 检查 Postgres、Qdrant、Redis、storage root；返回 `ready` 或 `degraded` 及脱敏详情 |
| `GET` | `/api/v1/system/info` | 返回产品名、环境、storage 是否配置等非敏感摘要 |
| `GET` | `/api/v1/workspaces` | 分页列出 workspace，按创建时间倒序 |
| `POST` | `/api/v1/workspaces` | 创建 workspace；自动生成、去重 slug；返回 201 |
| `GET` | `/api/v1/workspaces/{workspace_id}` | 返回单个 workspace；不存在时返回 404 |

可选但推荐的边界 smoke：提供只读 capability 信息，证明产品可以经 adapter 读取 `academic_companion` 的非 LLM 元数据。它不调用 LLM、不读取 Qdrant、不复用原型 chat route；若实现成本超过最小 shell，应移出本 Stage，不阻塞基础壳验收。

Stage 1 不提供 workspace 删除，避免在 document/index 等所有权语义出现前过早定义级联清理。

### 6.3 数据库与 workspace

首个 migration 仅创建 `workspaces`：

| 字段 | 要求 |
|---|---|
| `id` | UUID 字符串主键 |
| `name` | 必填，最大 120 字符 |
| `slug` | 必填且唯一；由名称或显式输入生成，冲突自动追加后缀 |
| `description` | 可空文本 |
| `created_at` | 带时区时间戳 |
| `updated_at` | 带时区时间戳，更新时刷新 |

任何后续用户可见业务表都必须能直接或间接追溯到 workspace，但本阶段不提前设计 document、chunk、course、exercise 或 memory 表。

### 6.4 基础设施与本地文件

- Postgres：正式业务数据库，使用 named volume。
- Qdrant：仅纳入 Compose 和 readiness，不创建正式 collection，不写入向量。
- Redis：仅纳入 Compose 和 readiness，不实现 queue、worker 或权威状态。
- `storage/`：可由配置创建或检测的本地根目录；运行时文件不进入 Git。
- Neo4j：明确不纳入本阶段 Compose。

### 6.5 Web 工作台

首屏至少包含：

- 平台名称和 workspace 导航/列表；
- API、Postgres、Qdrant、Redis、storage 的状态区；
- workspace 创建表单，带客户端校验、加载态和服务端错误反馈；
- 当前 workspace 详情与为空的后续资料入口占位。

页面文案必须诚实说明尚未实现的资料能力；不得将待开发功能伪装成已可用能力。

### 6.6 可观察性与 review

- API 请求带 request ID，并在日志中可关联。
- 启动日志仅输出非敏感配置摘要。
- `/health` 与 `/ready` 的语义必须区分。
- 在 `docs/01-platform-stage-1-self-host-shell/reviews/` 建立并维护 review 记录。

## 7. 明确不做

- 登录、多用户、权限、OAuth、删除 API。
- 文件上传、PDF/Markdown/TXT 解析、OCR、Office/网页批量导入、ingestion job、worker、chunk、embedding、Qdrant 写入。
- agent chat、SSE 产品接口、课程阅读器、知识图谱、练习、记忆闭环、run/cost analytics。
- Neo4j、反向代理、HTTPS、域名与云部署。
- 为既有八股或 LeetCode 资产设计专用数据模型。

这些不是永久否决：资料导入与问答会在 Platform Stage 2 的两个切片中按已确认路线实现；本 Stage 的目标是先建立承载它们的产品壳。

## 8. 建议实现顺序

1. 创建 `apps/api`、`apps/web`、`storage` 与产品依赖文件，确认 framework/product 依赖隔离。
2. 建立 API app factory、settings、结构化日志、`/health` 和 `/ready`。
3. 接入 Postgres、SQLAlchemy、Alembic，并实现 `workspaces` migration。
4. 实现 workspace schema、service、router 与 API 合约测试。
5. 实现 Web workbench、状态读取、workspace 列表和创建流程。
6. 增加 Dockerfile、Compose、`.env.example` 与 self-host runbook。
7. 执行迁移、测试、构建、Compose 启动和 Web/API smoke。
8. 对实质性代码 diff 运行 OCR/review，并归档结论。

## 9. 验证计划

| 类别 | 最低验证 | 通过标准 |
|---|---|---|
| API | `python -m pytest apps/api/tests -q` | workspace、health、ready、错误路径均有测试 |
| Migration | 对干净 Postgres 执行 upgrade | 创建表成功，重复运行无意外 |
| Web | `npm.cmd run lint` 与 `npm.cmd run build` | 均退出成功，无 TypeScript 错误 |
| Compose | `docker compose config` | 配置可解析，不含真实密钥 |
| 实际栈 | `docker compose up --build` | 五服务启动；Web 可访问；workspace 可创建并持久化 |
| Review | OCR/review 记录 | 结论、采纳项、未采纳项和复验结果完整 |

本机缺少 Docker、Node 或服务凭据时，不得伪造通过；必须记录原因、已完成的替代验证和未覆盖风险。

## 10. 风险与处理

| 风险 | 处理 |
|---|---|
| product 代码污染 framework/domain 层 | 仅在 `apps/` 写产品代码，使用 adapter 或公开接口依赖资产 |
| schema 过早膨胀 | 首个 migration 只含 `workspaces` |
| readiness 泄露运行细节 | 返回状态和脱敏详情，不返回 URL、密码、token、原始 traceback |
| Compose 过早承担业务复杂度 | Qdrant/Redis 仅做连通性与状态检查，不创建 worker/job |
| Web 退化为展示页或 chat UI | 以 workspace 操作和系统状态为首屏验收对象 |
| 误仓库代码被直接带入 | 以采用矩阵逐项重实现、测试和复核，不整体复制 |

## 11. 需要确认的 gate

确认本规格即表示接受：FastAPI + SQLAlchemy + Alembic + React/Vite/TypeScript；Postgres-first；五服务 Compose；workspace-first Web；产品 API 不继承原型 chat 路由；以及 Stage 1 不做 ingestion/chat/worker。

确认后才能进入产品业务代码实现。

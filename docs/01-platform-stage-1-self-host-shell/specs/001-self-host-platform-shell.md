# Spec 001：Self-Host 平台壳

状态：草案；实现前需要明确确认
日期：2026-07-10

## 目标

围绕现有 framework 与 academic 资产建立可 self-host 的产品应用。首屏是 operational workspace workbench，而不是双模式 chat 应用。

## 产品边界

`hello_agents/` 为可复用 framework；`academic_companion/` 为可复用 academic/domain 资产与原型参考；`apps/api` 与 `apps/web` 为产品代码。

产品业务状态属于 Postgres；Qdrant 是可重建的派生索引基础设施；Redis 是非权威的协调基础设施。原型内存 session 和内置数据目录均不得成为产品事实来源。

## 范围内

- 带独立依赖与测试的 `apps/api` FastAPI 应用。
- 带独立 npm lockfile 的 `apps/web` React/Vite/TypeScript 应用。
- Postgres、Qdrant、Redis、API、Web 五项 Docker Compose 服务。
- Postgres migration 与最小 `workspaces` 表。
- workspace 的 list、create 与 get API。
- 产品存活检查、readiness 与非敏感 system-info 接口。
- 只读 academic capability/catalog adapter：证明产品能依赖 `academic_companion`，但不把产品代码移入其中，也不调用 LLM。
- 展示 readiness、workspace 列表、workspace 创建和诚实空状态的 Web workbench，为后续资料能力预留位置。
- request ID，以及结构化、非敏感的服务端日志。
- Stage 专属验证命令、review 记录与 self-host runbook。

## 范围外

- 认证、多用户权限、删除语义和 OAuth。
- 上传、解析、OCR、批量导入、job、chunk、embedding 或 Qdrant 写入；这些属于 Platform Stage 2 的切片。
- Agent chat、SSE 产品接口、course reader、知识图谱、练习、间隔重复及 run/cost analytics。
- Neo4j、worker 服务、HTTPS/reverse proxy 和云部署。
- 针对现有八股或 LeetCode 资产的专用数据模型。

## 仓库布局

实现将新增 `apps/api/learn_platform_api`、`apps/api/alembic`、`apps/api/tests`、`apps/api/requirements.txt`、`apps/api/Dockerfile`、`apps/web`、根目录 `docker-compose.yml` 和被忽略的运行时 `storage/`。包名刻意区别于误仓库，使正确仓库建立自己的产品身份。

## API 合约

| 方法 | 路径 | 必需行为 |
|---|---|---|
| `GET` | `/health` | 仅进程级存活检查；不探测依赖 |
| `GET` | `/ready` | 报告 Postgres、Qdrant、Redis 和 storage root 为 `ready` 或 `degraded`；不得返回凭据或服务 URL |
| `GET` | `/api/v1/system/info` | 返回非敏感产品名、环境和 storage 已配置标识 |
| `GET` | `/api/v1/workspaces` | 分页列出 workspace，最新优先 |
| `POST` | `/api/v1/workspaces` | 创建 workspace，并保证 slug 碰撞安全 |
| `GET` | `/api/v1/workspaces/{workspace_id}` | 返回单个 workspace 或 404 |
| `GET` | `/api/v1/capabilities` | 只读 framework/academic 能力类别；不得调用 LLM |

`workspaces` 含 `id`、`name`、唯一 `slug`、可空 `description`、`created_at` 和 `updated_at`。本 Stage 故意不提供 workspace 删除。

## Web 合约

首屏必须是可用 workbench：workspace 导航与选中态；不暴露后端地址的系统 readiness；具有客户端校验与服务端错误展示的 workspace 创建；以及为后续资料能力留位、但不虚假宣称已实现的当前 workspace 空状态。

Stage 1 不通过原型 `/api/chat` 接口连接 Web，也不将 chat composer 置于产品中心。

## 交付与验证

实现验收必须按适用情况记录 API 测试、Web lint/build、`docker compose config` 及 `docker compose up --build`。最终 runbook 必须说明前置条件、环境变量、migration 命令、本地操作者 URL、关闭方式和 data volume 行为。实质性代码变更须执行 `AGENTS.md` 中的 review 工作流；OCR 结果或有意识地不执行 review 的决定必须记录在本 Stage 的 `reviews/` 目录。

## 验收说明

- 产品 API 自己拥有版本化合约。原型 route 从未作为产品 API 发布，因此不承诺兼容。
- Compose 验证必须使用干净配置与 named service volume。
- 实际运行栈验收必须确认 Web 可加载、workspace 创建经 Postgres 持久化，且 `/ready` 能区分健康与降级依赖。

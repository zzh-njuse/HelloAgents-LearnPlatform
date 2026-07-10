# ADR 001：应用技术栈与原型桥接

状态：提议；实现前需要明确确认
日期：2026-07-10

## 背景

正确仓库已有可复用 Python framework 和已提交的 academic 原型，却还没有产品应用边界。误仓库展示过一个可行的 Stage 1 shell，但它基于不同仓库状态创建，不能整体移植。

## 决策

| 层次 | 决策 |
|---|---|
| API | FastAPI、Pydantic Settings、版本化 `/api/v1` 产品路由 |
| 持久化 | SQLAlchemy 2.x 同步 session、Alembic、Psycopg 3、Postgres |
| Web | React、Vite、TypeScript、npm、提交 lockfile |
| 运维 | Docker Compose 管理 Postgres、Qdrant、Redis、API 与 Web |
| 日志 | 带 request ID、结构化且脱敏的服务端日志 |
| 依赖所有权 | 根元数据继续仅服务 framework；`apps/api/requirements.txt` 与 `apps/web/package.json` 分别拥有应用依赖 |

产品 API 将位于 `apps/api/learn_platform_api`，并通过只读 adapter 边界使用 `academic_companion`。Stage 1 不挂载或改写原型 chat router，也不以调用 LLM 作为 health 或 capability 测试。

## 理由

- FastAPI 适合 Python framework 边界；独立应用 manifest 避免 framework 用户被迫安装 Web/数据库依赖。
- 同步 SQLAlchemy 足以支撑小型 workspace CRUD；在后台 job 出现前避免过早引入 async database 复杂度。
- Postgres 从第一条 migration 起建立已确认的产品事实来源；Qdrant 和 Redis 保持为辅助服务。
- Vite/React 适合 operational SPA，并可选择性借鉴原型展示思路，而不继承 chat-first 信息架构。
- 产品自行拥有新的版本化 API 合约，避免把原型 CORS、异常原文、Qdrant URL 暴露和内存 session 变成公共默认行为。

## 后果

- Stage 1 会引入小型 monorepo 结构和多个验证命令。
- 根 `uv.lock` 修复与 framework 测试依赖策略仍是独立后续工作，不与应用依赖管理混在一起。
- 产品代码可 import 稳定的 framework/domain 接口，但不得在 `hello_agents` 或 `academic_companion` 中加入产品状态或产品 route 语义。
- 未来 chat/SSE 需要独立 spec 与合约测试，之后才可采用或演化原型信封。

## 本 Stage 不采用的方案

- 直接复制误仓库 Stage 1 树：其基线假设和包身份不同。
- 将 `academic_companion/api` 作为产品网关：它以原型为中心、依赖隐式、且含不安全的运行细节。
- SQLite-first 部署：与已接受的 Postgres 事实来源 gate 冲突。
- async SQLAlchemy、worker 和 job：推迟到 ingestion 使其必要时。
- chat-first Web：产品是学习平台，不是双模式 chat 应用。

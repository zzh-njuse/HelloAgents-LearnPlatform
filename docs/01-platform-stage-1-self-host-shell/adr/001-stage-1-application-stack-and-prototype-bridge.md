# ADR 001：Stage 1 应用技术栈、分层与原型桥接

状态：提议；经人工确认后生效
日期：2026-07-10
适用阶段：Platform Stage 1

## 1. 背景

正确仓库以 `hello_agents/` Python framework 为核心，另有 `academic_companion/` 学习/研究领域原型及其 API/Web。它们展示了不少可复用能力，但尚未构成可 self-host 的产品：没有独立产品应用层、Postgres migration、workspace 所有权根、Compose 拓扑或工作台入口。

误仓库曾实现 Legacy Phase 1 平台骨架，证明了一个可行方向，但其文件、依赖和命名均基于错误仓库基线。正确仓库需要吸收“做法”，而不是复制“文件”。

Stage 0R 已接受下列约束：

- 产品定位是资料驱动的学习平台，不是双模式 chat 应用。
- `hello_agents`、`academic_companion` 与 product app 是三个不同层次。
- Postgres 是业务事实来源；Qdrant 可重建；Redis 非权威。
- 现有 API/Web 是待吸收原型，不是最终入口。
- 既有八股和 LeetCode 数据是测试/演示资产，不驱动专用产品模型。

## 2. 决策摘要

Stage 1 采用 FastAPI + SQLAlchemy 2.x 同步 session + Alembic + Psycopg 3 + Postgres，配合 React + Vite + TypeScript，并用 Docker Compose 启动 Postgres、Qdrant、Redis、API 和 Web。

产品代码放入 `apps/`，产品 API 使用自己的 `/api/v1` 合约；不把原型 chat router 升格为产品入口。应用依赖与 framework 依赖分开管理，Stage 1 不引入 worker、ingestion 或 Neo4j。

## 3. 决策细节

### 3.1 仓库分层与包命名

采用以下布局：

```text
hello_agents/             可复用 framework
academic_companion/       可复用领域资产和原型
apps/api/learn_platform_api/  产品 API
apps/web/                 产品 Web
```

`learn_platform_api` 是正确仓库的新产品包名，不沿用误仓库的名称。产品状态、HTTP 语义、数据库访问和 Web 交互必须由 `apps/` 拥有。产品可以 import 稳定的 framework/domain 接口，但不得反向把产品概念写回资产层。

### 3.2 API、数据库与 migration

采用 FastAPI 作为产品 API 框架，SQLAlchemy 2.x 同步 engine/session 作为 Stage 1 数据访问方式，Alembic 管理 schema 演进，Psycopg 3 连接 Postgres。

选择同步 SQLAlchemy 的原因是：workspace CRUD、readiness 和 migration 没有高并发异步数据库需求；同步模型的 session 管理、测试和故障定位更直接。未来 ingestion worker 出现后，可在独立 ADR 中评估异步或 worker 专用访问层，而不提前复杂化所有 API。

首个 migration 仅创建 `workspaces`。它是产品中所有后续用户可见数据的归属根，不提前设计 document/chunk/course/exercise/memory schema。

### 3.3 配置与依赖所有权

采用 Pydantic Settings 读取 `.env` 和环境变量。应用配置必须支持运行环境覆盖，且公开接口和日志只返回脱敏摘要。

依赖边界如下：

| 依赖类别 | 所在位置 | 说明 |
|---|---|---|
| Framework runtime | 根 `pyproject.toml` 与根锁文件 | 不强迫 framework 使用者安装 Web/数据库包 |
| Product API | `apps/api/requirements.txt` | FastAPI、SQLAlchemy、Alembic、Psycopg、Pydantic Settings 等 |
| Product Web | `apps/web/package.json` 与 lockfile | React/Vite/TypeScript 及 UI 依赖 |

根 `uv.lock` 当前漂移以及 framework 测试依赖未声明，是 0R-A 已记录的独立问题；本 ADR 不以“为了跑产品 API”为由扩张根 framework 依赖。

### 3.4 基础设施职责

| 服务 | Stage 1 职责 | 明确不承担 |
|---|---|---|
| Postgres | workspace 及后续产品事实 | 可被向量索引替代的检索数据 |
| Qdrant | 启动、连通性和 readiness 预留 | 产品事实、正式 collection、向量写入 |
| Redis | 启动、连通性和未来协调预留 | 权威业务状态、已实现 queue/worker |
| storage root | 本地路径配置与可写检查 | 上传/导入流程 |

Compose 包含这五个服务，使 self-host 拓扑先成型；Neo4j、worker、反向代理与 HTTPS 不属于 Stage 1。

### 3.5 产品 API 与原型的桥接

Stage 1 采用“新 API，窄 adapter”的桥接策略：

- `/health`、`/ready`、`/api/v1/system/info` 和 workspace 路由由产品 API 新建。
- 不复用 `academic_companion/api` 的 `/api/chat`、`/api/chat/stream`、`/api/knowledge/status` 或根发现接口。
- 不把原型的内存 session、原始异常、Qdrant URL、固定 CORS 端口和同步 research streaming 带入产品默认值。
- 仅允许可验证、无 LLM 调用、无产品状态副作用的 adapter smoke；若无稳定资产接口，宁可延后，而不制造假 adapter。

这意味着原型 API 没有向后兼容承诺。后续需要 chat 或 SSE 时，必须独立制定产品合约、鉴权/会话语义、事件格式、重试和 contract test。

### 3.6 Web 定位

采用 React + Vite + TypeScript，并使用 npm 管理前端依赖。首屏是工作台：workspace 列表/创建/选择及系统 readiness。它不是 landing page，也不是 chat-first 页面。

可选择性借鉴原型的 Markdown 渲染、流式消息和本地开发代理思路，但 Stage 1 不复制原型 chat 组件，也不连接原型 API 路由。

### 3.7 可观察性与 review

产品 API 使用 request ID、结构化日志和脱敏输出。`/health` 只反映进程存活；`/ready` 反映依赖可用或降级状态。每次实质性代码变更按照 `AGENTS.md` 运行 OCR/review 并保留记录；OCR 是审查辅助，不取代人工判断。

## 4. 影响

### 正向影响

- 保持 framework、领域资产与产品代码的所有权清晰。
- 从 Stage 1 起建立可迁移的 Postgres 数据纪律，而不让 Qdrant/Redis 反客为主。
- 以 Compose 形成真实 self-host 路径，同时把 ingestion 复杂度延后。
- 用 workspace-first Web 让产品形态清晰可演示，避免再次落入 chat demo。

### 成本与约束

- 仓库将从单一 Python package 变为含 Python app、Node app 与 Docker 的多组件仓库。
- CI 和本地验证会增加 API、Web、migration、Compose 四类命令。
- 应用依赖和 framework 依赖必须长期维护边界。
- 原型能力不会被立即暴露给最终用户；短期内产品功能较少，但结构更稳。

## 5. 未采用的替代方案

### 5.1 直接复制误仓库 Stage 1 代码

不采用。其 package 名、依赖、路径和测试假设属于错误基线。我们复用其架构意图、测试场景和运维意识，但按照本仓库 spec/ADR 重写。

### 5.2 将 `academic_companion/api` 直接作为产品 API

不采用。它缺少独立依赖 manifest，使用内存 session，暴露原始异常与 Qdrant URL，且 API/Web 以 chat-first 原型为中心。

### 5.3 Flask 或 Django

不采用。Flask 对版本化 API、类型化 schema 和 OpenAPI 支持较弱；Django 对当前 API-first、agent/RAG 集成目标过重。FastAPI 与既有 Python 资产衔接最自然。

### 5.4 FastAPI 加 async SQLAlchemy

暂不采用。它具有长期价值，但 Stage 1 的简单 CRUD 不足以抵消 async session、migration 和测试的额外复杂度。

### 5.5 SQLite-first

不采用为正式 self-host 主路径。它可在未来作为 demo/dev 便利模式评估，但不能替代已确认的 Postgres 事实来源。

### 5.6 只做后端，或将 Web 做成 chat 页面

不采用。Stage 1 的目的就是从“库/原型”进入“产品”。没有 workspace-first Web 入口，仍只是 API demo；以 chat 作为首屏又会偏离学习平台定位。

## 6. 生效条件

本 ADR 与 [Spec 001](../specs/001-self-host-platform-shell.md) 一并经人工确认后生效。生效后，采用矩阵中标注为“采用并重写”的项目才可进入实现；其余原型和误仓库代码继续只作参考。

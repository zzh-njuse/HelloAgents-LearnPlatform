# 数据库与部署形态开发计划

版本日期：2026-07-08

目标：把当前 demo 里的分散持久化能力，收束成一个可开发、可自托管、后续可演进到 hosted service 的数据架构。

## 1. 当前仓库真实情况

当前项目还没有平台级业务数据库。已有的是 agent 框架层的存储能力：

| 存储 | 当前代码位置 | 当前用途 | 主要问题 |
|---|---|---|---|
| SQLite | `hello_agents/memory/storage/document_store.py` | 作为部分记忆的权威存储，默认写入 `./memory_data/memory.db` | 表结构偏 memory demo，不适合作为平台业务库 |
| Qdrant | `hello_agents/memory/storage/qdrant_store.py` | 存 memory 向量、RAG chunk 向量 | 是检索索引，不应承担业务事实来源 |
| Neo4j | `hello_agents/memory/storage/neo4j_store.py` | 语义记忆里的实体和关系 | 依赖重，第一版产品不应强依赖 |
| 本地文件目录 | `RAGTool.knowledge_base_path`，默认 `./knowledge_base` | `add_text` 会落成 markdown 文件，文档解析也依赖原始文件路径 | 缺少文件版本、归属、删除、引用定位和权限模型 |
| 环境变量 | `hello_agents/core/database_config.py` | Qdrant/Neo4j 连接配置 | 缺少平台层数据库配置和统一配置入口 |

一个很重要的判断：当前的 SQLite/Qdrant/Neo4j 是框架能力演示，不是未来产品的数据底座。后续要保留它们的经验，但需要新建平台层数据模型。

## 2. 核心原则

第一版必须把“权威数据”和“派生索引”分清楚：

- Postgres 业务库：self-host 正式主路径的事实来源。用户、workspace、资料、chunk 元数据、课程、练习、学习记录、agent run、成本、任务状态都以它为准。
- SQLite：保留为 demo/dev/local-only 可选模式，不作为第一版 self-host 主路径承诺。
- Object storage/本地 volume：原始文件和解析后的规范化文本。文件不是数据库字段的附属品，而是可版本化资产。
- Qdrant：向量索引。它可以删除重建，不作为唯一事实来源。
- Redis：队列和短期缓存。它可以丢，不作为事实来源。
- Neo4j：后置可选图索引。第一版用关系表表达概念和边，等查询需求稳定再引入 Neo4j。

第一版要避免“每个能力都上一个数据库”。数据库越多，部署越重，开源用户越容易卡死在安装阶段。

## 3. 推荐产品形态

我建议把项目第一目标定为“开源自托管学习 agent 平台”，而不是一上来做 SaaS。

原因：

1. 成本和隐私压力小。用户自己提供 LLM key、数据库和文件存储，你不需要立刻处理计费、合规、滥用、数据泄漏。
2. 面试叙事更自然。你能展示 Docker Compose、schema migration、任务队列、可观测性，而不是只展示网页 demo。
3. 对学习资料更友好。用户上传的课程 PDF、笔记、代码往往有版权或隐私，自托管更容易被接受。
4. 开发闭环更短。先让本机和 VPS 跑起来，再考虑 hosted service。

推荐三种部署档位：

| 档位 | 面向用户 | 数据库形态 | 目标 |
|---|---|---|---|
| Demo/dev mode | 面试、本机体验、快速开发 | SQLite + 本地文件 + 可选 Qdrant | 低门槛试用，不作为正式 self-host 主路径 |
| Self-host mode | 开源主路径 | Docker Compose: Postgres + Qdrant + Redis + 本地 volume/MinIO | 用户拉取后自行配置，真正可长期使用 |
| Hosted mode | 未来服务化 | 托管 Postgres + Qdrant Cloud/自托管 + S3/R2/OSS + Redis | 你作为服务提供者运营多租户服务 |

第一版主推 Self-host mode。Demo/dev mode 只做快速体验和开发便利，Hosted mode 只在架构上预留。

## 4. 作为服务提供者时，数据库是什么

如果未来你提供 hosted service，你实际运营的是：

- `Postgres`：权威业务库。最重要。
- `Qdrant`：向量检索索引。按 workspace 过滤。
- `Object storage`：原始文件、解析文本、导出包、日志附件。
- `Redis`：队列、任务锁、短缓存。
- `Observability storage`：可以先放 Postgres，后续再接 Prometheus/Loki/OpenTelemetry。

你不应该直接把用户的学习资料只塞进向量库。正确顺序是：

1. 原始文件进 object storage。
2. 文件元数据和任务状态进 Postgres。
3. 解析后的 markdown/text 进 object storage，必要的 chunk 内容和定位信息进 Postgres。
4. embedding 后的向量和检索 payload 进 Qdrant。
5. 课程、练习、学习记录、记忆、成本和 trace 都进 Postgres。

这样 Qdrant 出问题时，可以从 Postgres + object storage 重建索引；用户删除资料时，也能做完整可审计删除。

## 5. 用户提供什么数据，分别怎么存

### 5.1 用户身份和配置

| 数据 | 存放 | 说明 |
|---|---|---|
| 用户账号、邮箱、昵称 | Postgres `users` | Self-host 可先单用户或本地账号 |
| workspace 成员和角色 | Postgres `workspace_members` | Hosted mode 必须有 |
| 用户偏好 | Postgres `user_settings` | 语言、学习风格、默认模型 |
| LLM provider 配置 | 环境变量优先；Hosted 才入库加密 | 开源自托管建议用 `.env`，不要把 API key 默认写 DB |
| 用户本地 UI 状态 | 浏览器 localStorage | 只存主题、折叠状态、最近页面，不存学习资料正文 |

### 5.2 用户上传资料

| 数据 | 存放 | 说明 |
|---|---|---|
| 原始 PDF/Markdown/代码/图片 | Object storage 或本地 volume | 路径由 `source_documents.storage_uri` 引用 |
| 文件 hash、大小、类型、状态 | Postgres `source_documents` | 去重、重试、删除、版本管理 |
| 解析后的 markdown/text | Object storage | 可重用、可下载、可重新 chunk |
| 解析质量报告 | Postgres `document_parse_reports` | 乱码、空页、低文本密度、表格丢失 |
| chunk 内容和定位 | Postgres `document_chunks` | `source_span`、`heading_path`、`content_hash` |
| chunk embedding | Qdrant | payload 带 `workspace_id`、`document_id`、`chunk_id` |

### 5.3 平台生成内容

| 数据 | 存放 | 说明 |
|---|---|---|
| 知识点 | Postgres `concepts` | 名称、解释、重要程度、难度 |
| 知识点关系 | Postgres `concept_edges` | 先修、相关、包含、易混 |
| 课程章节树 | Postgres `course_sections` | 有版本和发布状态 |
| 学习页正文 | Postgres `lessons` 或 object storage + DB metadata | 长正文可放 storage，DB 存版本和引用 |
| 引用关系 | Postgres `lesson_citations` | lesson/exercise 到 chunk 的可审计链接 |
| 练习题、答案、讲解 | Postgres `exercises` | 题型、难度、rubric、来源 |
| 生成质量评分 | Postgres `generation_evaluations` | 是否可发布，失败原因 |

### 5.4 用户学习过程

| 数据 | 存放 | 说明 |
|---|---|---|
| 阅读、提问、答题、复习事件 | Postgres `learning_events` | 时间线和分析来源 |
| 答题记录 | Postgres `exercise_attempts` | 原始答案、得分、反馈 |
| 掌握度 | Postgres `concept_mastery` | workspace/user/concept 维度 |
| 错题本 | Postgres `review_items` | 可由答题记录派生，也可以单独建表 |
| 学习记忆 | Postgres `memories` + 可选 Qdrant | 稳定画像和长期记忆要可见、可删 |

### 5.5 Agent 运行和工程可观测性

| 数据 | 存放 | 说明 |
|---|---|---|
| agent run | Postgres `agent_runs` | 输入摘要、输出摘要、状态、耗时 |
| tool call | Postgres `tool_calls` | 工具名、参数摘要、结果摘要、错误 |
| token 和成本 | Postgres `cost_events` | provider、model、tokens、估算价格 |
| 后台任务 | Postgres `jobs` + Redis queue | Postgres 记录状态，Redis 执行调度 |
| eval cases/results | Postgres | 面试展示质量体系 |
| OCR/CR 审查记录 | Postgres `code_review_runs/findings` | 开发协作流程的证据 |

## 6. 用户数据有没有必要存在用户本地

有可能，但不应该成为第一版主路径。

第一版“本地”的推荐含义是 self-host：用户把服务、数据库和文件 volume 部署在自己的机器或 VPS 上。这样已经满足隐私和可控性，同时工程复杂度可控。

不建议第一版做真正 browser-local 或桌面本地数据库，原因：

- 资料解析、embedding、任务队列和大文件管理不适合只放浏览器。
- 浏览器本地存储容量和可靠性都不够。
- 本地与云同步会引入冲突解决、加密、备份、版本合并，复杂度过早。

可以预留一个后续模式：

| 模式 | 本地存什么 | 适合阶段 |
|---|---|---|
| Browser cache | UI 状态、最近打开章节、草稿 | 立即可做 |
| Self-host local volume | 原始文件、解析文本、Postgres volume、Qdrant volume | 第一版主路径 |
| Local-only desktop | SQLite/DuckDB + Qdrant local + Ollama | 后续隐私增强版 |
| Hybrid | 敏感资料本地，生成摘要同步云端 | 很后期 |

## 7. 第一版最小数据库方案

为了开源自托管容易，我建议第一版标准 Compose 只包含：

- `api`: FastAPI
- `web`: React/Vite 或 Next.js
- `worker`: 后台任务
- `postgres`: 权威业务库
- `qdrant`: 向量索引
- `redis`: 队列和锁
- `storage`: 先用本地 volume，后续可换 MinIO/S3

Neo4j 暂不进入默认 Compose。概念图谱先用 Postgres 表：

```text
concepts
concept_edges
section_concepts
document_concepts
```

等概念关系查询变复杂，再加 Neo4j adapter，把 Postgres 中的概念和边同步过去。

## 8. 建议的首批表

第一批不要建太多，但要把生命周期闭环跑通：

```text
users
workspaces
workspace_members
source_documents
document_versions
document_parse_reports
document_chunks
ingestion_jobs
concepts
concept_edges
course_sections
lessons
lesson_citations
exercises
exercise_attempts
learning_events
memories
agent_runs
tool_calls
cost_events
eval_cases
eval_results
```

其中最先实现的最小闭环可以只有：

```text
users
workspaces
source_documents
document_chunks
ingestion_jobs
course_sections
lessons
agent_runs
tool_calls
cost_events
```

按照最新大阶段路线，练习和记忆进入阶段 4；eval、成本和质量指标进入阶段 5。阶段 2/3 只保留支撑资料管线和章节体验所必需的最小表，避免过早扩大 schema。

## 9. Qdrant 设计

Qdrant 第一版使用单 collection + payload 过滤：

```json
{
  "workspace_id": "...",
  "document_id": "...",
  "document_version_id": "...",
  "chunk_id": "...",
  "chunk_type": "source|lesson|exercise|memory",
  "source_path": "...",
  "heading_path": "...",
  "start": 123,
  "end": 456,
  "content_hash": "...",
  "permission_scope": "workspace"
}
```

不要每个用户一个 collection。那样 demo 好理解，但后续索引管理、迁移、监控都会更麻烦。真正需要强隔离时，可以 hosted enterprise mode 再做 per-tenant collection。

关键约束：

- Qdrant payload 中必须有 `workspace_id`。
- 所有检索必须带 workspace filter。
- 删除文档时，先标记 Postgres 状态，再按 `document_id/version_id` 删除 Qdrant 向量。
- Qdrant 可重建，所以不要只在 Qdrant 里保存 chunk 正文。

## 10. 文件存储设计

Self-host 第一版可以先用本地目录：

```text
data/
  uploads/
    <workspace_id>/<document_id>/<version_id>/original.<ext>
  parsed/
    <workspace_id>/<document_id>/<version_id>/content.md
  exports/
  logs/
```

数据库只保存 URI、hash、mime type、大小、解析状态，不保存大文件 blob。

后续迁移到 S3/R2/OSS/MinIO 时，只需要替换 storage adapter，不改业务表。

## 11. 开源用户自行配置数据库是否更容易

是，而且应该作为第一版主路径。但要注意“自行配置”不能等于“让用户自己理解所有数据库”。

推荐体验：

1. `git clone`
2. 复制 `.env.example` 为 `.env`
3. 填 LLM provider key
4. `docker compose up -d`
5. 打开 Web UI

数据库默认由 Compose 创建：

- Postgres 默认账号密码在 `.env`。
- Qdrant 默认本地 volume。
- Redis 默认本地。
- 文件默认本地 volume。

用户可以进阶替换：

- `DATABASE_URL=postgresql://...`
- `QDRANT_URL=...`
- `QDRANT_API_KEY=...`
- `STORAGE_BACKEND=s3`
- `S3_BUCKET=...`

这比一开始做 hosted service 容易，也更适合作为开源主项目。

## 12. Hosted service 的预留点

虽然第一版主推 self-host，但 schema 设计要预留 hosted：

- 所有业务表必须有 `workspace_id` 或能通过外键追到 workspace。
- 所有用户可见资源必须有 owner/workspace 权限判断。
- `source_documents` 要有删除状态和删除时间。
- API key 不明文入库；Hosted mode 使用加密字段或外部 secret manager。
- `agent_runs` 和 `tool_calls` 只存参数摘要，敏感正文可脱敏或单独加密。
- 成本事件必须按 workspace 聚合。
- 导出和删除要能按 workspace 全量执行。

## 13. 开发顺序

推荐从数据库开始的实际开发顺序：

1. 写 ADR：第一版采用 self-host Docker Compose，Postgres 为权威业务库，Qdrant 为派生索引，Neo4j 后置。
2. 新建 `apps/api`，接入配置系统，支持 `DATABASE_URL`、`QDRANT_URL`、`STORAGE_ROOT`。正式 self-host 默认使用 Postgres；SQLite 仅作为 demo/dev 便利模式。
3. 引入 Alembic，创建首批最小表。
4. 实现 storage adapter：先 local filesystem。
5. 实现 document ingestion job：上传文件 -> 记录 `source_documents` -> 解析 -> 写 parsed file -> 写 `document_chunks` -> 写 Qdrant。
6. 实现删除/重建索引：从 Postgres 和 storage 重建 Qdrant，而不是依赖 Qdrant 自身。
7. 给 ingestion 做 trace：`agent_runs`、`tool_calls`、`cost_events`。
8. 再做 Course Reader 的最小页面。

资料管线阶段第一张真正该写的 spec 建议是：

`docs/03-stage-2-material-ingestion/specs/001-storage-and-ingestion.md`

在此之前，阶段 1 应先写平台骨架 spec，例如：

`docs/02-stage-1-self-host-platform/specs/001-self-host-platform-skeleton.md`

它应该明确：

- 文件上传接口。
- 表结构。
- 本地 storage 路径规范。
- Qdrant payload 契约。
- 删除和重试语义。
- 失败状态和错误展示。
- 测试用例。

## 14. 当前结论

最推荐路线：

> 以开源自托管为第一产品形态。用户拉取项目后用 Docker Compose 自行启动 Postgres、Qdrant、Redis 和本地文件 volume；用户自己提供 LLM key。你作为服务提供者的 hosted mode 先只做架构预留，不作为第一阶段目标。

这条路线最符合当前项目状态，也最适合作为面试主项目：它既不是玩具 demo，也不会过早掉进 SaaS 运营复杂度。

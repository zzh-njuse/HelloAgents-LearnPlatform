# Spec 001：单文件资料入库与引用检索

状态：已接受，进入实现
确认日期：2026-07-11
日期：2026-07-11
适用阶段：Platform Stage 2 Slice 1

## 1. 评审结论摘要

本规格定义 Stage 2 的第一条完整用户路径：用户在既有 workspace 中上传一份 PDF、Markdown 或 TXT，平台异步完成解析、切块、embedding 和 Qdrant 索引，并通过不调用 LLM 的检索 API 返回可定位到文档版本与 chunk 的引用证据。

本切片的难点不是“能把文本塞进向量库”，而是建立可恢复的资料生命周期：原始字节、业务状态、任务状态、chunk 正文、派生索引和用户可见错误分别由谁拥有，以及重复消息、失败重试、删除和索引重建时如何保持一致。

## 2. 背景与现状

Stage 1 已提供：

- `workspaces` 权威表和 workspace-first Web；
- FastAPI、SQLAlchemy、Alembic 与 Postgres；
- local storage root、Qdrant、Redis、API、Web 的 Compose 拓扑；
- `/health`、`/ready`、request ID 和脱敏日志；
- workspace list/create/get API。

当前尚无上传、document schema、worker、正式 Qdrant collection 或产品检索合同。`hello_agents/rag/pipeline.py` 和 `academic_companion` ingestion 只能作为能力参考：它们包含宽泛 parser、隐式 fallback、环境变量耦合和原型 payload，不能直接成为产品资料生命周期。

## 3. 目标

让单用户 self-host 环境中的一个 workspace 拥有第一份可追溯资料，并证明以下闭环：

```text
上传
  -> Postgres 创建 document/version/job
  -> 原始文件原子写入 storage
  -> Redis 传递 job ID
  -> worker 解析、切块、embedding、索引
  -> Postgres 标记 ready
  -> 用户查询并获得引用证据
```

## 4. 用户故事

### US-1 上传资料

作为用户，我可以在当前 workspace 上传一份受支持文件，立即看到资料记录和处理状态，而不需要等待解析完成。

### US-2 查看处理进度和失败原因

作为用户，我可以区分等待、运行、成功、排队失败和处理失败，并获得脱敏、可行动的错误说明。

### US-3 显式重试

作为用户，我可以对失败 job 发起重试。重复点击或 Redis 重复投递不会生成重复 chunk 或重复索引点。

### US-4 带引用检索

作为用户，我可以输入问题或关键词，获得按相关度排序的资料片段。每个结果都能定位到 workspace、document、version、chunk、标题路径和字符区间。

### US-5 删除资料

作为用户，我删除资料后，新的默认列表和检索必须立即排除它；Qdrant 和 storage 的物理清理由后台继续完成，失败可重试。

## 5. 成功标准

- 单个 PDF、Markdown 或 TXT 能从上传进入 `ready`。
- 上传接口在完成持久化和 enqueue 尝试后返回 `202`，不在请求线程执行解析或 embedding。
- Postgres 保存 document、version、parse report、chunk、job 和 query trace 的权威状态。
- 原始文件和规范化解析文本位于 storage，数据库和 API 不返回宿主机绝对路径。
- Qdrant 只保存向量与最小定位 payload；清空 collection 后可以从 Postgres/storage 重建。
- Redis 丢失、重复消息或短暂不可用不会丢失 job 事实，也不会破坏已完成结果。
- 所有检索都强制带 workspace filter，并回读 Postgres 排除非 ready、已删除或版本不匹配的结果。
- 删除在权威事务提交后立即对列表和检索生效。
- Web 提供资料列表、单文件上传、状态、失败重试、删除确认和检索结果引用定位。

## 6. 不变量

- `source_documents.workspace_id` 不可为空；任何资料查询先确定 workspace。
- 一个 document 可以有多个不可变 version，但 Slice 1 上传只创建首个 version。
- chunk 必须属于明确的 document version；不得只用文件名或 Qdrant point 表示归属。
- job 状态以 Postgres 为准；Redis/RQ 状态只用于诊断。
- Qdrant point ID 从稳定 chunk ID 派生，重复 upsert 必须覆盖而不是追加。
- `ready` 只能在原始文件、解析产物、chunk 事务和 Qdrant upsert 全部成功后设置。
- 删除状态优先于派生索引状态；cleanup 失败不能让资料重新可检索。
- 日志不得记录上传正文、完整查询文本、embedding 向量、凭据或 provider 原始响应。

## 7. 范围内

### 7.1 文件边界

| 类型 | 识别方式 | Slice 1 行为 |
|---|---|---|
| PDF | 扩展名与 MIME 双重校验 | 支持含文本层 PDF；没有可用文本时返回 `ocr_required` |
| Markdown | `.md` / `text/markdown` | 保留标题层级并规范化文本 |
| TXT | `.txt` / `text/plain` | 解码为 UTF-8 规范文本，无法可靠解码时失败 |

默认限制：单文件最大 25 MiB，空文件拒绝，原始文件名仅作显示信息，storage 路径只由服务端 ID 生成。服务端必须校验实际文件头或解析结果，不能只信浏览器 MIME。

### 7.2 权威数据模型草案

#### `source_documents`

| 字段 | 合同 |
|---|---|
| `id` | UUID 字符串主键 |
| `workspace_id` | 必填外键，索引 |
| `display_name` | 用户可见名称，默认取安全化原文件名 |
| `lifecycle_status` | `active`、`deleted` |
| `current_version_id` | 当前可见 version；初始处理完成前可空 |
| `created_at/updated_at/deleted_at` | 带时区时间 |

#### `document_versions`

| 字段 | 合同 |
|---|---|
| `id` | UUID 字符串主键 |
| `document_id` | 必填外键 |
| `version_number` | document 内从 1 递增，唯一 |
| `processing_status` | `uploaded`、`queued`、`processing`、`ready`、`failed` |
| `original_filename`、`mime_type`、`byte_size`、`sha256` | 上传事实 |
| `original_storage_uri` | storage 相对 URI |
| `parsed_storage_uri` | 成功后保存规范化文本的相对 URI |
| `parser_key/parser_version` | 可复现解析器标识 |
| `embedding_model/embedding_dimension` | 索引兼容合同 |
| `created_at/ready_at` | 带时区时间 |

#### `document_parse_reports`

每个 version 可按 job attempt 保存多条报告，包含 parser、页数/字符数、warning codes、脱敏 error code/message 和完成时间；`(document_version_id, attempt_number)` 唯一。结构化 warnings 使用 JSON，不保存 traceback 或原始文件内容。

#### `document_chunks`

| 字段 | 合同 |
|---|---|
| `id` | 稳定 UUID 字符串主键 |
| `document_version_id` | 必填外键，索引 |
| `ordinal` | version 内顺序，唯一 |
| `content` | 权威 chunk 正文 |
| `content_hash` | 规范化内容哈希 |
| `heading_path` | 可空标题路径 |
| `start_offset/end_offset` | 相对规范化解析文本的字符区间 |
| `token_count` | 可空估算值，不作为切块事实 |

#### `ingestion_jobs`

记录稳定 job ID、workspace、version、job type、状态、幂等键、attempt count、可重试时间、lease/heartbeat、脱敏错误和时间戳。详细状态由 ADR 002 定义。

#### `rag_query_traces`

记录 workspace、查询哈希、top-k、过滤条件摘要、候选/返回数量、延迟、模型/collection 版本与时间。默认不保存完整查询正文。

### 7.3 API 草案

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/documents` | 列出未删除资料及当前版本状态 |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents` | multipart 单文件上传；返回 document、version、job，状态 202 |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | 返回资料、版本和最新 job 摘要 |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | 权威软删除并创建 cleanup job；返回 202 |
| `GET` | `/api/v1/workspaces/{workspace_id}/ingestion-jobs/{job_id}` | 返回脱敏 job 状态 |
| `POST` | `/api/v1/workspaces/{workspace_id}/ingestion-jobs/{job_id}/retry` | 对允许状态重试同一业务 job；返回 202 |
| `POST` | `/api/v1/workspaces/{workspace_id}/rag/query` | 仅检索，不调用 LLM；返回结果、citations 和 trace ID |

所有嵌套资源必须同时匹配 path 中的 workspace；不匹配统一按 404 处理，避免泄露跨 workspace 资源存在性。

### 7.4 检索响应合同

```json
{
  "trace_id": "uuid",
  "query": "用户查询",
  "results": [
    {
      "score": 0.82,
      "text": "权威 chunk 正文",
      "citation": {
        "document_id": "uuid",
        "document_version_id": "uuid",
        "chunk_id": "uuid",
        "document_name": "示例资料.pdf",
        "heading_path": ["第二章", "2.1"],
        "start_offset": 1200,
        "end_offset": 1780
      }
    }
  ]
}
```

Qdrant 命中只提供候选 chunk ID 和 score。API 必须批量回读 Postgres，重新验证 workspace、document lifecycle、version ready 状态，并以 Postgres chunk 正文组装响应。

### 7.5 Web 工作流

- 当前 workspace 增加“资料”视图，不另建 chat-first 首页。
- 上传控件接受单文件并显示大小/类型错误。
- 资料列表展示文件名、类型、大小、处理阶段、更新时间和可操作错误。
- `queue_failed`/`failed` 提供显式重试；运行中禁止重复提交。
- 删除必须确认；确认后立即从默认列表和检索中消失。
- 检索结果以片段和引用定位为主，不伪装成自然语言答案。

## 8. 失败模式

| 场景 | 权威结果 | 用户可见行为 |
|---|---|---|
| workspace 不存在 | 不写文件、不建记录 | 404 |
| 文件类型/大小不合法 | 不写权威记录 | 422，稳定错误码 |
| storage 写失败 | 事务回滚或记录失败并清理临时文件 | 503/500，禁止留下可见半成品 |
| Postgres 成功但 enqueue 失败 | job=`queue_failed` | 资料保留，可显式重试 |
| parser 失败 | version/job=`failed`，保留原文件和 parse report | 显示脱敏错误，可重试 |
| 扫描 PDF | `failed: ocr_required` | 明确需要未来 OCR extension |
| embedding/Qdrant 失败 | job/version 不得 ready | 可重试，重复 upsert 安全 |
| worker 崩溃 | lease 超时后可重新 claim | 状态可见，不自动宣称成功 |
| Redis 重复消息 | 同 job/attempt 幂等执行 | 不产生重复 chunk/point |
| Qdrant 返回陈旧 point | Postgres 回读过滤 | 不返回已删除或非当前数据 |
| cleanup 失败 | document 仍保持 deleted | 默认不可见，后台可重试 |

## 9. 明确不做

- 图片 OCR、扫描 PDF 识别、Office、网页、Git、音视频和万能 parser。
- 批量上传、目录监视、压缩包展开和 URL 抓取。
- LLM 自然语言回答、MQE、HyDE、reranker 和 agent chat。
- 课程、章节、练习、长期 memory、Neo4j 和多用户鉴权。
- 自动覆盖同名 document 或隐式创建新版本。
- 复用 prototype collection、prototype memory payload 或现有八股/LeetCode 专用结构。

## 10. 建议实现顺序

1. 接受本 Spec 与 Stage 2 ADR。
2. 增加 product settings、依赖和 Alembic migration。
3. 实现 storage adapter、上传事务与 document read API。
4. 引入 RQ worker 和 Postgres job 状态机，先用测试 parser 跑通 job。
5. 实现 TXT/Markdown/PDF parser 与确定性 chunker。
6. 实现 embedding adapter、Qdrant repository、索引与重建。
7. 实现检索回读、citation 和 query trace。
8. 实现资料 Web 工作流。
9. 增加删除/cleanup、失败重试、Compose worker 和端到端验证。

## 11. 验证计划

| 类别 | 最低验证 |
|---|---|
| Schema | 干净数据库 upgrade；从 Stage 1 `0001` upgrade；约束和索引检查 |
| Upload | 三种小文件成功；空文件、超限、伪扩展名、扫描 PDF 失败 |
| Job | enqueue failure、重复消息、worker crash、retry、lease recovery |
| Storage | 临时文件原子 rename；相对 URI；失败清理；路径穿越测试 |
| Chunk | 固定 fixture 产生稳定 chunk ID、顺序、offset 和 heading path |
| Qdrant | workspace filter、重复 upsert、删除过滤、清空后重建 |
| Retrieval | 每个结果能回读到有效 version/chunk；删除后立即不返回 |
| Web | 上传、状态刷新、失败重试、删除确认、引用定位和响应式布局 |
| Compose | 增加 worker 后实际启动；API/worker 不并发执行 migration |
| Review | schema、删除、队列、上传和容器变更进入 OCR 与人工 gate |

## 12. 需要确认的 Gate

确认本规格表示接受：Slice 1 包含单文件异步入库、显式重试、权威软删除、检索与引用；Postgres 保存 chunk 正文；Qdrant 命中必须回读验证；扫描 PDF 以 `ocr_required` 失败；DashScope 作为默认 embedding provider；自然语言回答留到 Slice 2。

# Platform Stage 1 总结与 Stage 2 输入

日期：2026-07-10
状态：实现、OCR 评审、人工 Web 核验与本地验收完成；作为 Stage 2 文档工作的输入

## 实际完成

- 建立 `apps/api/learn_platform_api` 产品 API，与 `hello_agents`、`academic_companion` 保持单向依赖边界。
- 建立 FastAPI settings、request ID、结构化脱敏日志、`/health`、`/ready` 和 system info。
- 建立 SQLAlchemy workspace 模型、Alembic `0001` migration，以及 list/create/get API。
- 建立 React/Vite/TypeScript workspace-first 工作台，支持状态展示、workspace 列表、创建和选择。
- 建立 Postgres/Qdrant/Redis/API/Web 五服务 Compose、API/Web Dockerfile、Nginx 同源代理和本地 storage root。
- 建立 self-host runbook、API 测试、响应式视觉 QA 和 Stage review 记录。

## 未实现且符合范围

- 未实现上传、parser、OCR、批量导入、worker、embedding 或 Qdrant 写入。
- 未实现 agent chat/SSE 产品接口、课程、练习、memory 迁移或 Neo4j。
- 未将原型 API/Web 固化为产品合约。
- 未为八股/LeetCode fixture 设计专用模型。

## 验收结论

五服务实际栈已启动并通过：migration 为 `0001`，`/ready` 为 `ready`，Web 返回 HTTP 200，workspace 可经 API/Web 创建，并在 API 重启后由 Postgres 恢复。API 测试 `7 passed`，framework 离线回归 `155 passed, 4 skipped`，Web lint/build 通过。

## Stage 2 输入

Stage 2 Slice 1 可以从以下已稳定边界开始：

- 所有资料、document version、ingestion job 与检索权限必须归属 workspace。
- Postgres 保存 document/job/chunk 元数据和状态事实；Qdrant 只保存可重建向量索引。
- Redis 可用于非权威 job 协调，但任务状态必须回写 Postgres。
- 首个资料入口接入现有 workspace 工作台，不另建 chat-first 首屏。
- 先实现单文件 PDF/Markdown/TXT 的异步入库、检索和引用证据；再进入批量导入与带引用 LLM 回答。
- OCR、Office、网页/Git 导入作为 parser 扩展评审项，不从架构中永久排除，也不挤入第一个核心切片。

进入 Stage 2 前仍需独立编写并确认 ingestion schema、job 幂等/重试、文件所有权、删除语义和索引重建 ADR。

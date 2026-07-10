# Legacy 实现与仓库恢复总结

日期：2026-07-10

## 用途

本文压缩保存两类历史：

1. 2026 年 5 月在正确仓库完成的 Academic Companion 能力原型。
2. 2026 年 7 月从误仓库恢复高层设计并重新对齐正确仓库的过程。

旧计划和逐日开发报告已经删除。当前代码是实现事实，本文只保留仍影响后续决策的成果、限制和经验。

## Legacy Phase 1：RAG 与 MCP 基础

代表提交：`f39cff0`

完成成果：

- 建立 `hello_agents/embedding/`、`hello_agents/rag/`、`hello_agents/storage/qdrant_store.py` 和 `hello_agents/mcp/`。
- 将 embedding、Qdrant、RAG pipeline 与 MCP client/server 纳入 framework。
- 为后续 Academic Companion 提供可调用的检索和外部工具基础。

保留限制：

- 这些接口以 framework/demo 便利性为中心，不等于产品级资料生命周期。
- 可选依赖和运行环境没有形成产品 app 独立依赖边界。

## Legacy Phase 2：学习模式

代表提交：`3197ab2`

完成成果：

- 建立 `academic_companion` 学习模式、RAG retrieval、UserModel、Assessor 和学习 Skill。
- 接入 CS 八股与 LeetCode 数据，形成可演示的学习 Agent。
- 建立本地/云 embedding 与 Qdrant 相关配置和 ingestion 入口。

保留限制：

- 学习状态主要是本地文件或会话对象，不是 workspace 级产品事实。
- 内置题库适合测试和演示，不作为新产品 schema 的设计中心。

## Legacy Phase 3：研究模式与 Memory

代表提交：`4390a27`、`9b24189`

完成成果：

- 建立 search/filter/analyze/synthesize 多 Agent 管线和 ResearchOrchestrator。
- 接入 arXiv、Semantic Scholar、research notes 和结构化 pipeline context。
- 增强 framework Memory、Qdrant、本地 embedding 和 session 能力。

保留限制：

- 外部学术 API 的稳定性、配额和可选依赖需要隔离。
- orchestrator 和 memory 仍是领域原型，不拥有产品 workspace、权限或持久化合同。

## Legacy Phase 4：API 与 WebUI 原型

代表提交：`b51f03b`

完成成果：

- 建立 `academic_companion/api` FastAPI 原型，支持 learning/research chat、SSE 和 knowledge 状态。
- 建立 `academic_companion/webui` React/Vite 原型，支持模式切换、chat、thinking、tool call 和 research step 展示。
- 研究 orchestrator 增加 streaming event 输出。

保留限制：

- API 使用进程内 session，缺少产品 app 依赖、数据库和部署边界。
- WebUI 是 chat-first 原型，不是最终学习工作台或 Course Reader。
- 它们需要先固化 contract，再由 product app 吸收；不直接作为最终入口。

## 误仓库产生的成果

误仓库中形成了两类有价值资产：

- 高层设计：资料驱动学习平台、self-host first、Postgres/Qdrant/Redis 分工、阶段门禁和 Agent 协作方式。
- 参考实现：FastAPI + Postgres + Alembic + React + Docker Compose 的 Stage 1 平台壳，以及 Stage 2 ingestion 设计。

2026-07-10 执行的恢复步骤：

- `b51f03b`：先保存正确仓库已有 API/Web 和 dirty 成果。
- `3d8c7f6`：导入四份高层指导文档。
- `de6338e`：基于正确仓库重新分析产品边界。
- `087a4cb`：确认 Stage 0R Spec 与三层产品 ADR。

误仓库代码没有被迁入。它继续作为候选实现证据，必须在 Stage 1 spec/ADR 下逐项评估。

## 已确认的长期决策

- 主产品是资料驱动的学习平台，不是双模式聊天应用。
- `hello_agents`、`academic_companion` 是可复用已有资产；product app 拥有产品入口和状态。
- Postgres 是产品事实来源，Qdrant 是可重建索引，Redis 是非权威队列。
- `academic_companion/api` 与 `academic_companion/webui` 是待吸收原型。
- 八股/LeetCode 仅作为测试与演示材料，不主导产品数据模型。
- 历史能力阶段称 Legacy Phase；新产品交付称 Platform Stage。

## 被删除的旧文档

以下内容已由本文和四份当前指导文档替代：

- Academic Companion 旧立项书。
- Legacy Phase 1-4 的计划、开发报告和 WebUI 计划。
- RAG/MCP 单独集成报告。
- 首次双仓迁移矩阵与重新分析过程稿。
- 高层文档导入 provenance 说明。

删除不影响追溯。删除前的完整版本可从提交 `087a4cb` 读取，例如：

```powershell
git show 087a4cb:docs/phase-3-research-mode-plan.md
git show 087a4cb:docs/project-proposal-academic-ai-companion.md
git show 087a4cb:docs/phase-0R-correct-repository-reanalysis.md
```

## 对后续工作的约束

- 不从旧报告复制“已通过”结论到当前阶段，验证必须在当前依赖和代码上重跑。
- 不让 prototype 路由、内存 session 或 chat-first UI 反向定义产品架构。
- 不整提交 cherry-pick 误仓库 Stage 1。
- 下一次现状评估以当前四份指导文档、Stage 0R Spec/ADR 和代码事实为输入。

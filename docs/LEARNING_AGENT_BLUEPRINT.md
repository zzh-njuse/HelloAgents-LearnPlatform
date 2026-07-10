# HelloAgents 学习平台蓝图

版本日期：2026-07-10

状态：当前产品指导文档

## 1. 产品定位

HelloAgents Learn 是一个资料驱动、可 self-host 的个人学习 Agent 平台。

用户在 workspace 中接入学习资料，平台完成资料处理、引用检索、章节组织、辅导问答、练习、学习记忆和效果评估。产品追求三个长期特征：

- **可解释**：回答、课程和练习能够显示资料引用或明确标注生成来源。
- **可维护**：长任务有状态、可重试，数据有事实来源，索引可以重建。
- **可评估**：检索、生成、学习效果、延迟和成本有可重复的评测方式。

它不是 chat-first 应用。聊天是学习页中的辅导能力，不是首页和唯一交互。

## 2. 当前仓库事实

### 2.1 `hello_agents` framework

当前可复用能力包括：

- `hello_agents/core/`：LLM、message、streaming、session 和 lifecycle。
- `hello_agents/agents/`：Simple、ReAct、Reflection、PlanSolve 等 Agent 范式。
- `hello_agents/tools/`：Tool、ToolRegistry、ToolResponse、filter、Task、Skill、文件工具。
- `hello_agents/context/`：history、token、truncation 和 GSSC context builder。
- `hello_agents/embedding/`：local、TF-IDF 和 factory。
- `hello_agents/rag/`、`hello_agents/storage/qdrant_store.py`：分块、embedding、Qdrant 检索。
- `hello_agents/memory/`：working、episodic、semantic、perceptual memory 和存储适配。
- `hello_agents/mcp/`：MCP client/server。
- `hello_agents/observability/`：trace logger。

framework 当前由根 `pyproject.toml` 管理。产品 Web、数据库和部署依赖不应进入 framework 核心依赖。

### 2.2 `academic_companion` 领域能力

当前可复用能力包括：

- `LearningAgent`、`LearningSession`、`CSAssessor`、`AlgorithmAssessor`。
- UserModel、research notes 和 learning/research 配置。
- CS/LeetCode RAG loader、retrieval tool 和 ingestion demo。
- search/filter/analyze/synthesize 多 Agent research pipeline。
- arXiv、Semantic Scholar 与 web search fallback。
- `cs-interview`、`leetcode-patterns`、`paper-reading` Skill。

这些是领域能力资产，不是完整产品状态系统。

### 2.3 API/Web prototype

当前 prototype 位于：

- `academic_companion/api`
- `academic_companion/webui`

它已经验证 learning/research chat、SSE、thinking、tool call 和 research step 等交互，但存在明确边界：

- session 使用进程内状态。
- 没有 workspace、数据库 migration、权限和后台任务。
- Web 是 chat-first 信息架构。
- API/Web 产品依赖尚未从 framework 依赖中正式分离。

prototype 需要先建立 contract inventory，再由 product app 渐进吸收。它不是最终入口。

### 2.4 测试与演示资料

`data/cs_fundamentals` 和 `data/leetcode` 是现成测试、评测和演示材料。

它们不主导用户资料 schema，不要求 Stage 1 导入 Postgres，也不需要专用产品生命周期。后续可以选择少量样本验证 RAG、citation、课程或练习能力。

## 3. 目标用户闭环

第一条完整用户路径：

1. 用户启动 self-host 服务并创建 workspace。
2. 用户上传一份 PDF、Markdown 或纯文本资料。
3. 平台显示上传、解析、分块、embedding 和索引状态。
4. 用户进入资料或章节页面，查看结构化内容和引用片段。
5. 用户针对当前资料提问，回答显示引用；资料不足时明确说明。
6. 平台生成少量练习，用户作答后得到反馈。
7. 平台记录薄弱点，并在下次进入 workspace 时推荐复习内容。

任何阶段都不应通过隐藏失败或伪造完整能力来提前宣称闭环完成。

## 4. 产品体验

### 4.1 页面结构

| 页面 | 第一责任 |
|---|---|
| Dashboard | workspace、最近学习、待处理任务和待复习内容 |
| Workspace | 当前空间的资料、课程、进度和入口 |
| Ingestion Center | 上传、处理状态、失败原因和重试 |
| Course Reader | 章节树、学习正文、引用、辅导和练习 |
| Tutor | 当前 workspace/章节内的带引用辅导 |
| Practice | 练习、作答、反馈和错题 |
| Review Queue | 薄弱点与复习计划 |
| Run Trace | Agent、tool、任务与错误轨迹 |
| Quality & Cost | eval、延迟、token 和成本 |

Stage 1 只实现 Dashboard/Workspace 的最小产品壳。其他页面按路线图逐步加入。

### 4.2 交互原则

- 第一屏是工作台，不是营销页或全屏聊天框。
- 处理状态和失败原因始终可见。
- 引用可以定位到资料、版本和片段。
- 高风险操作显示影响范围，不静默删除。
- 开发者 trace 与普通学习界面分开。
- 页面服务于重复学习操作，保持安静、密集和可扫描。

## 5. 系统分层

### 5.1 三层模型

```text
apps/web
  -> apps/api
  -> academic_companion
  -> hello_agents
```

| 层 | 责任 |
|---|---|
| `hello_agents` | 通用 Agent runtime、LLM、Tool、Context、Memory/RAG 基础抽象 |
| `academic_companion` | 学习/研究 Agent、教学策略、领域 Skill 和能力适配 |
| product app | workspace、资料、课程、练习、任务、trace、最终 API/Web 和部署 |

依赖只能从产品层向领域层和 framework 层流动。framework 不得反向依赖产品代码。

### 5.2 在线请求

```text
Web -> Product API -> workspace context
    -> domain adapter -> Agent/Tool/LLM
    -> response/citation/trace -> Web
```

产品 API 负责鉴权或单用户边界、输入验证、事实数据和对外合同。领域 Agent 不直接拥有 HTTP 或数据库业务语义。

### 5.3 后台任务

```text
API 创建业务记录和 job
  -> Redis enqueue
  -> worker 执行 parse/chunk/embed/generate/evaluate
  -> storage/Postgres 写入事实
  -> Qdrant 更新派生索引
```

Redis 丢失不应抹掉业务任务事实；Qdrant 丢失应能重建。

## 6. Agent 角色

不建设一个拥有全部职责的万能 Agent。目标角色如下：

| 角色 | 输入 | 输出 | 产品阶段 |
|---|---|---|---|
| Ingestion service/agent | 文件与 metadata | parse report、chunk、索引状态 | Stage 2 |
| Course Architect | 资料与 chunk | 章节结构与知识点 | Stage 3 |
| Lesson Writer | 章节目标与引用 | 带引用学习内容 | Stage 3 |
| Tutor | 当前章节、问题、记忆 | 带引用回答和建议 | Stage 3 |
| Exercise Agent | 知识点与难度 | 题目、答案、rubric | Stage 4 |
| Review Coach | 学习事件与掌握度 | 复习队列与计划 | Stage 4 |
| Eval worker | case、输出、引用 | 质量结果 | Stage 5 |

现有 LearningAgent 和 research pipeline 是候选能力来源。是否直接复用、包装或拆分，由对应 Stage spec 决定。

## 7. RAG、Memory、Skill 与 MCP

### RAG

RAG 负责从用户资料或明确选择的测试资料中检索证据。产品层负责 document/version/chunk/citation 事实，Qdrant 只负责向量索引。

### Memory

Memory 负责偏好、薄弱点、学习事件摘要和长期学习上下文。产品 memory 必须可查看、纠正和删除；现有本地 memory 仅作为能力原型。

### Skill

Skill 保存稳定方法论，例如面试回答结构、算法模式和论文阅读流程。Skill 不保存用户状态，也不替代 RAG 事实。

### MCP

MCP 用于外部工具和资料源，例如学术搜索。产品主数据、内部 Postgres CRUD 和核心 RAG 路径不因“可工具化”而强制 MCP 化。

## 8. 产品数据原则

- Postgres 是 workspace、document、job、course、exercise、memory、trace 和 eval 的事实来源。
- 本地文件或对象存储保存原始文件和派生大文本。
- Qdrant 保存向量和最小定位 payload，可重建。
- Redis 用于队列、锁或缓存，不保存唯一业务状态。
- API key 放环境变量或 secret manager，不进入普通业务日志。
- 用户可见数据最终必须支持 workspace 级导出和删除。

详细方案见 [数据库与部署计划](./DATABASE_AND_DEPLOYMENT_PLAN.md)。

## 9. 当前产品起点

当前处于 **Platform Stage 0R**：

- 已保存正确仓库 checkpoint。
- 已确认三层模型和 self-host 数据原则。
- 正在整理文档、建立依赖/测试基线和 prototype contract inventory。
- 尚未建立最终 `apps/api`、`apps/web`、Postgres migration 或 Compose。
- 误仓库 Stage 1 代码仅作为候选实现证据。

## 10. 成功标准

### 第一可部署里程碑

- 新环境可按文档启动 Compose。
- Web/API/Postgres/Qdrant/Redis readiness 可验证。
- 可以创建 workspace。
- Product API 能通过一个明确 adapter 调用已有领域能力。

### 第一学习闭环里程碑

- 单份资料可上传、处理、重试和删除。
- 检索与回答能返回可定位引用。
- 章节、练习和学习事件有版本化事实记录。
- 最小 eval 可以在固定 fixture 上重复运行。

## 11. 非目标

- Stage 1 不做万能资料解析、完整课程、练习和多用户 SaaS。
- 不把八股/LeetCode 做成专门产品。
- 不把 Neo4j 作为默认部署依赖。
- 不为展示效果跳过任务状态、引用和事实来源。
- 不整目录复制误仓库代码来替代正确仓库分析。

## 12. 文档关系

- [Self-host 开发路线](./SELF_HOST_DEVELOPMENT_ROADMAP.md)
- [数据库与部署计划](./DATABASE_AND_DEPLOYMENT_PLAN.md)
- [Agent 协作开发流程](./AGENT_COLLABORATION_PLAYBOOK.md)
- [当前 Stage 0R](./00R-platform-baseline-reconstruction/README.md)
- [Legacy 与恢复总结](./history/LEGACY_AND_RECOVERY_SUMMARY.md)

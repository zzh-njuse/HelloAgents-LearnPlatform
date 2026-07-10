# 阶段 0R：正确仓库重新分析

日期：2026-07-10

状态：架构 gate 已确认，进入文档与验证阶段

## 1. 分析方法

本轮不从“如何把误仓库代码搬过来”出发，而从两个独立输入重新推导：

1. 正确仓库当前代码和 Git 历史代表已经存在的事实。
2. 导入的四份高层文档代表期望的产品运作模式与工程原则。

误仓库的阶段 1/2 实现和细节文档暂时只作为参考案例，不作为既定架构，也不决定正确仓库下一步必须复制哪些文件。

事实优先级：

```text
正确仓库当前代码与测试
  > 已确认的产品级 ADR/spec
  > 导入的高层目标与原则
  > 误仓库阶段实现和历史验证记录
```

## 2. 高层文档真正定义的产品

四份文档形成的核心不是一组文件布局，而是一套产品运作模式：

> 一个以资料驱动的个人学习 Agent 平台。用户在 workspace 中接入资料，平台异步完成解析、索引和知识结构化，再提供章节学习、带引用辅导、练习、记忆、复习与效果评估。

必须保留的产品原则：

- **不是 chat-first**：聊天是 Course Reader 和当前章节中的辅导能力，不是产品首页或唯一入口。
- **资料驱动**：回答、课程、练习和知识点应能追溯到资料或明确标注模型生成。
- **workspace 是边界**：资料、课程、练习、记忆、运行记录和成本都归属 workspace。
- **异步长任务**：解析、embedding、课程生成、练习生成和评测不应占用普通 HTTP 请求生命周期。
- **可解释、可维护、可评估**：引用、任务状态、失败重试、trace、eval 和成本是产品能力，不是后补日志。
- **self-host first**：第一产品形态是 Docker Compose；用户自己提供模型凭据，Hosted 只做架构预留。
- **权威数据分层**：Postgres 保存业务事实，本地文件或对象存储保存文件字节，Qdrant 是可重建索引，Redis 是非权威协调层。
- **框架与产品分层**：`hello_agents` 保持通用 runtime；产品业务不继续堆进 framework。
- **阶段门禁**：先 spec/ADR，再实现、测试、review 和人工确认；数据库、删除、权限、部署属于高风险变更。

## 3. 正确仓库当前事实

### 3.1 已有能力比高层文档描述得更完整

正确仓库已经有一套 `academic_companion` 领域实现：

- LearningAgent、LearningSession、Assessor 和 UserModel。
- research search/filter/analyze/synthesize agents 与 orchestrator。
- CS 八股和 LeetCode ingestion、RAG retrieval 与 Qdrant 接入。
- research notes、MCP 学术检索、三类学习/研究 Skill。
- GSSC 上下文、流式事件、Agent/Tool/Memory 等 framework 能力。
- FastAPI/SSE 与 React WebUI 原型，支持 learning/research 双模式。

因此项目不是高层文档所说的“只有框架、没有学习业务”。正确描述应是：

> 已经有较丰富的学习/研究能力原型，但尚未形成以 workspace、资料生命周期和 Course Reader 为中心的产品运行系统。

### 3.2 当前缺口是产品状态机，不是 Agent 数量

当前最关键的缺失：

- 没有产品级 workspace、document/version、job、course、exercise、attempt 和 trace 数据模型。
- 没有 Postgres migration、worker 和可重试任务状态。
- 现有 session 与部分 memory 仍依赖进程内字典或本地文件。
- 现有 WebUI 以聊天为中心，与高层文档的学习工作台/Course Reader 信息架构不一致。
- 现有 API 是 prototype server，没有明确的产品 app 依赖和部署边界。
- 内置八股/LeetCode 数据已经可检索，但没有与用户上传资料、workspace 权限和引用生命周期统一建模。
- 测试基线受本机缺失依赖影响，尚无可复现的一条命令覆盖 framework、product API 和 Web。

### 3.3 历史阶段编号已经冲突

正确仓库已有：

- Phase 1：RAG/MCP framework integration。
- Phase 2：Learning mode。
- Phase 3：Research mode。
- Phase 4：WebUI prototype。

导入路线图又定义：

- Stage 0：工程地基。
- Stage 1：Self-host 最小平台。
- Stage 2：资料驱动入口。
- Stage 3：章节化学习。
- Stage 4：练习、记忆与学习闭环。
- Stage 5：质量、成本与展示。

后续统一命名：

- 2026 年 5 月已有成果称为 **Legacy Phase 1-4**，代表能力原型演进史。
- 新产品路线称为 **Platform Stage 0-5**，代表 self-host 产品交付顺序。

这样不重写历史，也不再让“Phase 2”同时指两个完全不同的目标。

## 4. 重新推导的产品运行模型

### 4.1 在线请求路径

```text
apps/web
  -> apps/api
  -> workspace/session authorization
  -> product service
  -> academic_companion capability adapter
  -> hello_agents runtime / LLM / tools
  -> response + citation + trace
```

API 负责产品语义和权限；`academic_companion` 负责学习与研究能力；`hello_agents` 负责通用 Agent runtime。三层不能互相替代。

### 4.2 后台任务路径

```text
upload/generate request
  -> Postgres 创建业务记录和 job
  -> Redis enqueue
  -> worker parse/chunk/embed/generate/evaluate
  -> storage + Postgres 写入事实
  -> Qdrant 更新派生索引
  -> Web 查询或订阅状态
```

Redis 丢失不能导致业务事实丢失；Qdrant 丢失必须能从 Postgres 与文件存储重建。

### 4.3 推荐代码边界

```text
hello_agents/          通用 Agent framework
academic_companion/   学习、研究、RAG、Memory、Skill 领域能力
apps/api/              workspace、资料、课程、练习、任务、trace 产品 API
apps/web/              学习工作台与 Course Reader
data/                  内置种子知识库，不是用户上传目录
```

关键点不是是否使用 `apps/` 这个名字，而是产品状态、权限、持久化和部署不得继续隐藏在 demo 入口里。

## 5. 已有八股与 LeetCode 数据的定位

正确仓库已有的八股与 LeetCode 数据定位为现成测试、评测和演示材料，不作为新产品数据模型的设计中心。

约束如下：

- Stage 0R 不为这些数据单独设计所有权、版本、删除或权限模型。
- Stage 1 不要求把这些数据接入产品数据库。
- Stage 2 设计用户上传资料时，以真实 workspace 文档生命周期为准，不让已有题库格式反向决定 schema。
- 需要验证 RAG、citation、课程或练习能力时，可以选取少量现有数据作为 fixture。
- gitlink、许可和完整数据分发问题记录为仓库维护事项，但不阻塞产品分层和 Stage 1 文档工作。

## 6. 对现有原型的重新定位

### 6.1 `academic_companion/api`

它是能力验证入口，不直接等同于最终产品 API。应先用 contract tests 固化 learning/research/SSE 行为，再决定由产品 API 包装、拆分或替代。当前内存 session 不能成为 self-host 多进程产品状态。

### 6.2 `academic_companion/webui`

它提供可复用的聊天、thinking、tool call 和 research pipeline 组件，但 chat-first 页面结构不应成为产品信息架构。最终 Web 的中心应是 Dashboard、Workspace、Ingestion Center 和 Course Reader。

### 6.3 现有 RAG 与 memory

现有实现适合作为兼容层和算法参考，不应直接承担产品事实来源。产品层需要显式的 document/version/chunk/job/citation/memory schema，并通过 adapter 调用或逐步收敛现有能力。

### 6.4 误仓库阶段 1 骨架

它证明 FastAPI + Postgres + Alembic + React + Compose 的平台壳可运行，但它只是一个参考实现。正确仓库应先确认上述分层、API contract 和数据边界，再决定逐文件移植还是按正确仓库模式重建。

## 7. 新的阶段起点

### Platform Stage 0R：基线重建

完成条件：

- 正确仓库保持干净并有可回退 checkpoint。
- 高层目标文档带 provenance 导入。
- 历史 Phase 与新 Platform Stage 命名分开。
- 明确 framework、domain capability、product app 三层职责。
- 建立可复现依赖与测试基线。
- 记录八股/LeetCode 为非阻断的测试与演示资产。

### Platform Stage 1：最小产品壳

Stage 1 只证明：

- Compose 能启动 Web、API、Postgres、Qdrant、Redis。
- 可以创建 workspace。
- readiness 不泄露敏感部署信息。
- 产品 API 可以通过一个 adapter 调用已存在的简单 `academic_companion` 能力。
- 不在本阶段实现完整 ingestion、Course Reader、练习或 memory 迁移。

### Platform Stage 2：资料生命周期与引用检索

在 Stage 1 稳定后再定义上传、版本、解析、chunk、embedding、索引、删除、重试和 citation。产品合同以 workspace 用户资料为中心；八股/LeetCode 只作为可选 fixture 验证该合同。

## 8. 已确认的架构 gate

2026-07-10 已人工确认：

1. 主产品定位为学习平台，而不是双模式聊天应用。
2. 采用 `hello_agents` / `academic_companion` / product app 三层模型；前两层主要视为可复用已有资产。
3. Postgres 是产品事实来源，Qdrant 是可重建索引，Redis 是非权威队列。
4. `academic_companion/api` 与 `academic_companion/webui` 是待固化、吸收的原型，不是最终产品入口。
5. 八股/LeetCode 作为测试与演示材料，不为其做针对性产品设计，也不让其决定用户资料 schema。
6. 使用 Legacy Phase 与 Platform Stage 双命名，不修改历史文档含义。
7. 误仓库阶段 1 代码仅作为参考；先完成文档，Stage 1 spec/ADR 确认后再决定采用方式。

## 9. 下一步只做什么

gate 已确认，下一步仍然限定为文档和验证工作：

1. 编写正确仓库版 Platform Stage 0R spec，记录上述完成条件。
2. 编写产品边界 ADR，确认三层模型与 prototype 兼容期。
3. 建立依赖安装与测试基线，不修业务行为。
4. 把数据 gitlink/许可问题记录为非阻断仓库维护项。
5. 为现有 learning/research/SSE 原型补 contract inventory，作为后续迁移验收依据。

完成这些工作后，才重新制定 Stage 1 实施矩阵。首次双仓审计中的迁移矩阵继续保留，但不直接执行。

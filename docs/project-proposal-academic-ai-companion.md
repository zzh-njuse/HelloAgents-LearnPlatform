# Academic AI Companion — 项目立项文档

> **版本**: v0.2 (已整合原始RAG/MCP代码)
> **最后更新**: 2026-05-15
> **状态**: 架构设计完成，原始实现已分析，等待启动开发

---

## 1. 项目定位

### 一句话描述
基于 HelloAgents 框架构建的**学术 AI 伙伴**，深度融合 Memory、RAG、上下文工程、MCP、Skill、多 Agent 协作六大维度，覆盖"求职学习 + 论文学术"双场景。

### 目标用户
- **Primary**: 我自己（求职备战 + 毕业论文）
- **Secondary**: 面试展示（证明 Agent 工程能力）

### 为什么是"双模式"而非两个项目
1. 共享基础设施（RAG 知识库、Memory 系统、MCP 连接层）
2. 面试时可展示同一框架下单 Agent 与多 Agent 两种范式
3. 求职+论文是同一人同一时期的真实需求，场景天然统一

---

## 2. 原始框架实现分析（已获取）

框架作者在被删除的 `rag/` 和 `protocols/` 目录中留下了完整的 RAG 和协议实现。

### 2.0.1 RAG 原始实现 (`rag/`)

**数据模型** (`document.py`, 7.5KB):
- `Document` — 通用文档基类 (id, title, content, metadata, embedding)
- `TextDocument` — 纯文本；`CodeDocument` — 代码（按函数/类拆分）；`ImageDocument` — 图片（含 alt_text + OCR 文本）；`TableDocument` — 表格（DataFrame）
- `DocumentCollection` — 文档集合，支持合并、去重、元数据过滤

**核心管线** (`pipeline.py`, 43KB, 1300+ 行):
- `IngestionPipeline` — **摄入管线**

  ```
  Load → Chunking → Cleaning → Metadata Enrichment → Embedding → Storing (Qdrant)
  ```
  - Chunking 策略（4 种）:
    - `FixedChunker` — 固定大小，按字符数切分
    - `SentenceChunker` — 句子级，可配 overlap window
    - `SemanticChunker` — 基于相似度阈值检测语义边界
    - `HierarchicalChunker` — 递归拆分: doc → section → paragraph → sentence
  - Metadata 增强: `LLMMetadataEnricher` 用 LLM 生成标题、摘要、主题、关键词、实体（结构化 JSON 输出）
  - Embedding: 支持 OpenAI/text-embedding-3-small 和本地 sentence-transformers
  - Storing: Qdrant，支持 batch upsert + collection 管理

- `RetrievalPipeline` — **检索管线**

  ```
  Query → Transform → Vector Search (Dense) + BM25 (Sparse) → Fusion → Reranking → Post-processing
  ```
  - Query Transform:
    - `QueryDecomposer` — 复杂查询拆分为子查询，并行检索后合并
    - `HyDETransform` — 生成假设文档（HyDE），用假设文档的 embedding 检索
  - 双路检索:
    - Dense: Qdrant vector search + embedding
    - Sparse: BM25 (基于 `rank_bm25`)，内存索引
    - Fusion: RRF (Reciprocal Rank Fusion) 融合两路结果
  - Reranker（2 种）:
    - `LLMReranker` — LLM 逐条打分 0-100，支持 top_k 和 threshold 筛选
    - `DiversityReranker` — 基于 embedding 相似度实现 MMR 去重

- `QueryPipeline` — **联合管线**，RAG 检索 → LLM 生成，封装端到端流程

**关键设计亮点：**
- 管线可配置（PipelineConfig），支持保存/加载管线状态
- Chunk 级缓存（避免重复 embedding 和存储）
- LLM Metadata Enricher 让检索质量大幅提升（有标题/摘要/关键词的 chunk 检索更准）

### 2.0.2 协议原始实现 (`protocols/`)

**MCP** (`mcp/`):
- `MCPServer` — 服务端，装饰器式注册: `@mcp_server.tool(name, description, parameters)`
- `MCPServerConfig` — host + port + transport (streamable-http)
- **只有 Server 端，没有 Client 端** — 我们需要的是 Client（调用外部 MCP 服务如 arXiv API），需要自己写

**A2A** (`a2a/`, Google Agent-to-Agent Protocol):
- `A2AClient` — HTTP REST 客户端，向远端 Agent 发任务
- `A2AServer` — HTTP 服务端，暴露本地 Agent 能力
- `AgentCard` — 自描述（name, description, skills, tools, url, capabilities）
- 支持 streaming (SSE) + non-streaming

**ANP** (`anp/`, Agent Network Protocol):
- `ANPServer` + `ANPAgentCard` — JSON-LD 格式 Agent 能力声明
- 相比 A2A 更轻量，但 A2A 生态更好

### 2.0.3 对我们项目的影响

| 原始组件 | 复用策略 | 需要的改动 |
|---------|---------|-----------|
| `rag/pipeline.py` | **直接复用** | 增加中文 SentenceChunker，增加 bge-large-zh embedding 支持，注册为 Tool |
| `rag/document.py` | **直接复用** | 增加 LeetCode JSON 和 CS-Base Markdown 的数据加载器 |
| `protocols/mcp/` | **参考设计** | 仅 Server，需新建 MCPClient |
| `protocols/a2a/` | **可选加分项** | 研究模式子 Agent 通信可作为"进阶展示"，MVP 用框架 TaskTool 即可 |

---

## 3. 六大能力维度的深度落地

### 3.1 Memory — 四种类型全使用

| 记忆类型 | 框架组件 | 本项目中的使用 | 深度体现 |
|---------|---------|--------------|---------| 
| **短期记忆** | HistoryManager | 单次对话的消息历史 | 长对话自动压缩（Smart Summary），保留"用户对虚拟内存理解薄弱"等关键信息 |
| **长期记忆** | SessionStore | 跨天学习进度、论文调研进度 | 恢复会话时完整还原上下文+工具Schema一致性检查 |
| **摘要记忆** | Smart Summary | 压缩学习长对话保留关键发现 | 独立轻量 LLM 生成结构化摘要（已学/掌握/薄弱/待学） |
| **开发日志** | DevLog | 学习轨迹追踪 | 每日学习记录、论文调研决策链、知识盲区标记 |

**深度设计**：构建 UserModel，不存原始消息而存"用户知识图谱"（实体+掌握程度+最后复习时间），让 Agent 能自适应教学。

### 3.2 RAG — 多源检索 + 混合召回

**技术架构：基于原始 `rag/pipeline.py` 增强**

```
原始管线:
  IngestionPipeline:  Load → Chunk → Clean → Metadata(LLM) → Embed → Store(Qdrant)
  RetrievalPipeline:  Query → Transform(HyDE/Decompose) → Dense+BM25 → RRF Fusion → Rerank(LLM+MMR)

我们增强:
  ┌─ 中文 SentenceChunker (jieba 分句 + 语义边界检测)
  ├─ bge-large-zh-v1.5 embedding (开源，中文 SOTA)
  ├─ LeetCode JSON loader + CS-Base Markdown loader
  ├─ 注册为 Agent Tool (RAGRetrievalTool)
  └─ 与 ContextBuilder GSSC 管线对接 (检索结果 → Gather 阶段输入)
```

**知识源**：

| 知识源 | 数据量 | 格式 | Chunking 策略 |
|--------|--------|------|--------------|
| CS 八股（CS-Base） | 1000+图, 50万字 | Markdown | HierarchicalChunker: doc→chapter→section→paragraph |
| LeetCode 题库 | 2913题 | JSON | 每题一个 chunk（含描述+标签+难度+题解） |
| Agent/LLM 前沿知识 | 论文摘要集 | JSON | SemanticChunker: 按语义边界切分 |
| 论文PDF全文 | 用户自有 | PDF → PyMuPDF | Section-level chunking + overlap |

**深度设计**：
- Query Decomposer: "TCP三次握手和四次挥手的区别" → 拆为 3 个子查询分别检索再合并
- HyDE Transform: 用户问得模糊时，先生成假设答案，用假设答案的 embedding 去搜
- LLMReranker + DiversityReranker 串联: 先打分筛选 top-K，再 MMR 去重
- 上下文感知检索: 将用户对话历史中的"薄弱知识点"注入查询，提高检索相关性

### 3.3 上下文工程 — GSSC 管线实战

框架自带的 ContextBuilder 实现 Gather-Select-Structure-Compress：

```
[Gather]  RAG检索结果(Top-15 chunks) + Memory(最近3轮对话 + UserModel摘要) 
          + System Prompt(模式: 学习/研究) + Skill L1 metadata
          → 候选 ContextPacket 列表 (~30-50个包)

[Select]  对每个包计算 score = relevance * 0.4 + recency * 0.3 + importance * 0.3
          → MMR过滤 (λ=0.7, 保证知识点多样性)
          → Token预算填充 (128K窗口, 预留30%给Response)
          → 最终保留 Top-8~12 个包

[Structure] 
          [Role] 你是一个专注于{学习/研究}的AI助手
          [Task] {用户当前问题}
          [State] {用户知识状态: 已掌握/薄弱/待复习}
          [Evidence] {RAG检索到的知识点1, 2, 3...}
          [Context] {对话历史关键回合}
          [Output] 按{教学/学术}格式输出

[Compress] 超预算时按优先级截断 (Evidence优先保留, Context优先压缩)
```

**深度设计**：
- 学习模式预置一套 ContextConfig，研究模式预置另一套
- Evidence 区注入 RAG 检索的知识点（含来源、章节、难度）
- State 区由 UserModel 动态填充（不是硬编码）
- 长期对话中 Smart Summary 压缩旧历史到 State 区

### 3.4 MCP — 外部工具协议集成

**原始实现有 MCP Server，我们需新建 MCP Client + 业务 Tool 层。**

```
┌─────────────────────────────────────────────────────┐
│  Agent Tool 层 (hello_agents Tool 接口)               │
│  ArxivSearchTool / SemanticScholarTool / WebSearchTool│
├─────────────────────────────────────────────────────┤
│  MCP Client 层 (我们新建)                             │
│  - 连接管理 (connect/disconnect/reconnect)            │
│  - JSON-RPC 消息封装                                  │
│  - streamable-http transport                         │
│  - 错误处理 + 重试 + 超时                              │
├─────────────────────────────────────────────────────┤
│  外部 MCP Server / REST API                          │
│  arXiv API / Semantic Scholar / SerpAPI / ...        │
└─────────────────────────────────────────────────────┘
```

### 3.5 Skill — 渐进式知识外化

**使用框架已有 Skill**：
- `web-search/` — 网络搜索
- `web-reader/` — 网页内容读取
- `pdf/` — PDF 处理（论文阅读核心）
- `docx/` — 报告/论文导出

**新建 Custom Skill**：

| Skill | 内容 | 加载层级 |
|-------|------|---------|
| `cs-interview` | 面试备考方法论、答题框架、高频考点清单 | L1: 50 tokens → L2: ~2000 tokens |
| `paper-reading` | 三段式论文阅读法、批判性阅读清单、笔记模板 | L1: 30 tokens → L2: ~1500 tokens → L3: scripts/ |
| `leetcode-patterns` | 算法解题模式分类（双指针/滑动窗口/DP/树/图） | L1: 40 tokens → L2: ~2500 tokens |

**深度设计**：
- 所有 Skill 由 SkillLoader 统一管理
- L1 元数据在系统提示词中仅占 ~120 tokens
- Agent 通过 SkillTool 按需加载 L2（框架已有 SkillTool）
- 学习模式: `cs-interview` + `leetcode-patterns`；研究模式: `paper-reading` + `pdf`

### 3.6 多 Agent 协作 — 研究模式核心

**学习模式：单 Agent**
```
User → LearningAgent (ReActAgent)
         ├── RAGRetrievalTool → 检索知识库
         ├── Memory 工具 (4种) → 读写记忆
         ├── SkillTool → 加载学习方法论
         └── WebSearchTool (MCP fallback) → 补充未知内容
```
单 Agent 足够：学习是线性流程，检索→讲解→练习→答疑。

**研究模式：多 Agent 编排（PlanSolveAgent + TaskTool）**
```
User → ResearchOrchestrator (PlanSolveAgent)
         │
         ├─ Plan ─→ 分析用户需求 → 生成4步研究计划
         │
         ├─ Step 1 ─→ SearchAgent (ReActAgent, sub-agent via TaskTool)
         │              ├── MCP: ArxivSearch + SemanticScholar
         │              ├── RAG: 检查本地论文库
         │              └── 返回: 候选论文列表 (top 20, 结构化)
         │
         ├─ Step 2 ─→ FilterAgent (ReActAgent, sub-agent via TaskTool)
         │              ├── 读摘要 + 方法 + 实验结果
         │              ├── 评分维度: 相关度/新颖度/可靠性/可复现性
         │              └── 返回: 精选论文列表 (top 5, 含评分理由)
         │
         ├─ Step 3 ─→ AnalyzeAgent x N (ReflectionAgent, 并行 via TaskTool)
         │              ├── Skill: pdf (PDF提取) + paper-reading (方法论)
         │              ├── Read → Reflect → Re-read → Structured Summary
         │              └── 返回: 单篇论文结构化分析卡片
         │
         └─ Step 4 ─→ SynthesizeAgent (SimpleAgent, sub-agent via TaskTool)
                        ├── 汇总所有分析结果
                        ├── 生成: 文献综述 / 方法对比表 / 研究空白分析
                        ├── 引用管理 (BibTeX 输出)
                        └── 返回: 结构化调研报告 (支持 docx 导出)
```

**深度设计**：
- 不同 Agent 类型各司其职（ReAct 搜索和筛选、Reflection 分析、PlanSolve 编排、Simple 合成）
- 子 Agent 上下文隔离（不污染主 Agent HistoryManager）
- Tool Filter 控制子 Agent 权限（ReadOnlyFilter: SearchAgent 只能调 API 不能写文件；FullAccessFilter: SynthesizeAgent 可以写文件）
- 并行执行 AnalyzeAgent（同一篇论文的不同分析维度，或多篇论文同时分析）
- **加分项**: A2A 协议替代 TaskTool 做 Agent 间通信（标准化，面试展示加分）

---

## 4. WebUI 技术选型

### 决策：React 19 + TypeScript + Vite

**为什么不用纯 HTML/JS**：
- 本项目 UI 复杂度高：双模式切换、工具调用卡片、思考过程展开、代码/公式渲染
- React 的组件模型天然适合 Chat UI 的树状结构
- 生态系统成熟：react-markdown（公式+代码高亮）、shadcn/ui（工具卡片）
- 面试演示时现代技术栈加分

**技术栈**：
- React 19 + TypeScript + Vite
- shadcn/ui（组件库）
- react-markdown + KaTeX（公式 + 代码高亮）
- SSE (Server-Sent Events) — 框架已有 `core/streaming.py` 和 `examples/fastapi_sse_server.py`

**SSE 数据流**：
```
Browser (React) ←──SSE── FastAPI Server ←── Agent.arun_stream()
  EventSource        /api/chat/stream         StreamEvent (chunk, tool_call, thinking...)
```

---

## 5. 技术架构

```
┌──────────────────────────────────────────────────────────┐
│  WebUI Layer (React 19 + Vite)                            │
│  ┌───────────┐  ┌───────────┐  ┌───────────────────┐    │
│  │ 学习模式    │  │ 研究模式    │  │ 知识管理 (后台)     │    │
│  │ Chat UI    │  │ Multi-Agent│  │ RAG索引/记忆查看    │    │
│  └───────────┘  └───────────┘  └───────────────────┘    │
├──────────────────────────────────────────────────────────┤
│  API Layer (FastAPI)                                      │
│  /api/chat/stream  /api/chat/research  /api/knowledge    │
│  SSE streaming     Multi-agent orchestration   CRUD      │
├──────────────────────────────────────────────────────────┤
│  Application Layer (academic_companion/)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐│
│  │Learning   │  │Research   │  │RAG引擎   │  │Memory    ││
│  │Agent      │  │Orchestrator│  │(原rag/   │  │System    ││
│  │(ReAct)    │  │(PlanSolve) │  │pipeline) │  │(4种)     ││
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘│
├──────────────────────────────────────────────────────────┤
│  Framework Layer (hello_agents/ — 不改动)                  │
│  Agent基类 | HelloAgentsLLM | Tool系统 | ContextBuilder   │
│  SessionStore | TraceLogger | SkillLoader | Lifecycle     │
├──────────────────────────────────────────────────────────┤
│  Infrastructure                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐│
│  │ Qdrant    │  │ MCP Client│  │ Skill加载器│  │可观测性   ││
│  │ (向量DB)  │  │ (新建)    │  │ (渐进披露) │  │(Trace)   ││
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## 6. 项目目录结构（已确定）

```
HelloAgents/
├── hello_agents/            # 框架核心 (**不改动**)
│   └── ... 
├── rag/                     # 原始 RAG 实现 (直接复用, 少量增强)
│   ├── __init__.py
│   ├── document.py          # Document/TextDocument/CodeDocument 等
│   └── pipeline.py          # IngestionPipeline/RetrievalPipeline/QueryPipeline
├── protocols/               # 原始协议实现 (参考)
│   ├── mcp/                 # MCP Server (参考设计)
│   ├── a2a/                 # A2A Client+Server (加分项, MVP 不用)
│   └── anp/                 # ANP Server (参考)
├── academic_companion/      # ★ 我们的项目主体
│   ├── __init__.py
│   ├── config.py            # 项目配置 (LLM, Qdrant, MCP endpoints, 模式预设)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── learning_agent.py           # 学习模式: ReActAgent 封装
│   │   └── research/
│   │       ├── __init__.py
│   │       ├── orchestrator.py          # PlanSolveAgent 编排器
│   │       ├── search_agent.py          # 论文搜索 Agent (ReAct)
│   │       ├── filter_agent.py          # 论文筛选 Agent (ReAct)
│   │       ├── analyze_agent.py         # 论文分析 Agent (Reflection)
│   │       └── synthesize_agent.py      # 报告合成 Agent (Simple)
│   ├── rag_extensions/                 # RAG 增强 (基于 rag/pipeline.py)
│   │   ├── __init__.py
│   │   ├── loaders.py                  # 数据加载器 (CS-Base Markdown, LeetCode JSON)
│   │   ├── chinese_chunker.py          # 中文 SentenceChunker (jieba 分句)
│   │   └── rag_tool.py                 # RAGRetrievalTool (将RetrievalPipeline注册为Agent Tool)
│   ├── mcp_extensions/                 # MCP 扩展 (原只有Server, 我们补Client)
│   │   ├── __init__.py
│   │   ├── client.py                   # MCPClient (JSON-RPC + streamable-http)
│   │   └── tools/
│   │       ├── arxiv_search_tool.py     # arXiv API Tool
│   │       ├── semantic_scholar_tool.py # Semantic Scholar API Tool
│   │       └── web_search_tool.py       # 通用搜索 Tool (fallback)
│   ├── memory_extensions/              # Memory 增强
│   │   ├── __init__.py
│   │   └── user_model.py               # UserModel (用户知识图谱, 基于4种Memory)
│   ├── api/                            # FastAPI 后端
│   │   ├── __init__.py
│   │   ├── server.py                   # FastAPI 主入口 + CORS
│   │   ├── routes_chat.py              # /api/chat/stream (SSE), /api/chat/research
│   │   └── routes_knowledge.py         # /api/knowledge CRUD (后台管理)
│   ├── webui/                          # React 前端
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── components/
│   │   │   │   ├── ChatView.tsx        # 主聊天视图
│   │   │   │   ├── MessageCard.tsx     # 消息卡片 (文本/代码/公式渲染)
│   │   │   │   ├── ToolCallCard.tsx    # 工具调用展开卡片
│   │   │   │   ├── ThinkingBlock.tsx   # 思考过程折叠块
│   │   │   │   ├── ModeSwitcher.tsx    # 学习/研究模式切换
│   │   │   │   ├── ResearchPanel.tsx   # 多Agent流程可视化
│   │   │   │   └── KnowledgeManager.tsx # 知识库管理
│   │   │   ├── hooks/
│   │   │   │   └── useSSE.ts           # SSE 流式 hook
│   │   │   └── lib/
│   │   │       └── api.ts              # API 调用封装
│   │   └── ... (vite.config.ts, package.json, etc.)
│   └── skills/                         # Custom Skills (框架 SkillLoader 加载)
│       ├── cs-interview/
│       │   └── SKILL.md
│       ├── paper-reading/
│       │   └── SKILL.md
│       └── leetcode-patterns/
│           └── SKILL.md
├── data/                               # 知识库原始数据
│   ├── cs_fundamentals/                # CS-Base (xiaolincoding) 导入
│   └── leetcode/                       # neenza/leetcode-problems 导入
├── skills/                             # 框架自带 Skill (**不改动**)
│   └── ...
├── tests/                              # 测试
│   ├── test_rag_ingestion.py
│   ├── test_rag_retrieval.py
│   ├── test_learning_agent.py
│   └── test_research_agent.py
└── docs/
    └── project-proposal-academic-ai-companion.md  # 本文档
```

---

## 7. 知识库数据来源

### 已确认资源

| 知识源 | 资源 | 规模 | 许可证 | 用途 |
|--------|------|------|--------|------|
| CS 八股 | [CS-Base (xiaolincoding)](https://github.com/xiaolincoder/CS-Base) | 1000+图, 50万字, 中文 | 开源 | 学习RAG |
| CS 八股 | [CS-Wiki (Veal98)](https://github.com/Veal98/CS-Wiki) | 考研+面试, Java/C++ | 开源 | 补充 |
| LeetCode | [neenza/leetcode-problems](https://github.com/neenza/leetcode-problems) | 2913题, 结构化JSON | 开源 | 刷题RAG |
| LeetCode | [Kaggle: LeetCode Python Solutions](https://www.kaggle.com/datasets/theabbie/leetcode) | ~2300题 Python 题解 | CC0 | 补充题解 |
| 面试QA | [Kaggle: Technical QA Dataset](https://www.kaggle.com/datasets/atuldeshpande96/technical-question-answering-dataset) | DS/Algo/OS/CN/DB 问答对 | 开源 | 问答补充 |
| 论文 | arXiv API (实时 MCP) | 全领域 | 免费API | 研究检索 |
| 论文 | Semantic Scholar API (实时 MCP) | 全领域+引用图 | 免费API | 研究检索+引文分析 |

### 数据库摄入方案

```
基于 rag/pipeline.py 的 IngestionPipeline:

CS-Base:
  Loader: MarkdownDirLoader → 读各章节目录
  Chunker: HierarchicalChunker (doc→chapter→section→paragraph)
  Metadata: LLMMetadataEnricher (提取 title, topic, keywords, difficulty)
  Embedding: bge-large-zh-v1.5 (本地, 1024d)
  Store: Qdrant Collection "cs_fundamentals"
  索引字段: chapter(str), topic(str), difficulty(int 1-5)

LeetCode:
  Loader: LeetCodeJSONLoader → 解析 JSON
  Chunker: 每题一个 chunk（太长的题解按步骤切分）
  Metadata: 从 JSON 提取 id, title, difficulty, topics[], has_solution
  Embedding: bge-large-zh-v1.5
  Store: Qdrant Collection "leetcode"
  索引字段: id(int), difficulty(str), topics[](str)

经典论文:
  Loader: PDFDirLoader → PyMuPDF 提取文本
  Chunker: SectionChunker (按 Abstract/Intro/Method/Experiment/Conclusion 分段)
  Metadata: LLMMetadataEnricher (提取 title, authors, year, contributions, methods)
  Embedding: text-embedding-3-small (英文)
  Store: Qdrant Collection "papers"
  索引字段: year(int), authors[](str), arxiv_id(str)
```

---

## 8. 已解决的决策

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| 1 | Embedding 模型 | **bge-large-zh-v1.5** (中文) + **text-embedding-3-small** (英文) | 中文效果好且开源本地跑；英文论文用 OpenAI |
| 2 | RAG 代码来源 | **复用原始 `rag/pipeline.py`**，在此基础上增强 | 管线设计完整（多Chunker/双路检索/LLM Reranker/MMR），无需重写 |
| 3 | MCP 实现 | **原始只有 Server，我们新建 Client** | 我们需要的是调用外部服务（arXiv等），不是暴露自己 |
| 4 | 前端 MVP 范围 | **先 React 前端，不做命令行中间态** | 框架有完整的 SSE streaming 支持，React 集成成本不高 |
| 5 | 知识库首批规模 | **OS内存管理 + TCP/IP + 动态规划**，3个领域精选 | 每个领域数据完整，验证全流程再扩展 |
| 6 | 多 Agent 通信 | **框架 TaskTool 为主**，A2A 列为加分项 | TaskTool 已完整实现子Agent机制；A2A 是标准化协议，面试展示"我知道这个"即可 |

---

## 9. 开发阶段规划

### Phase 1: 基础设施搭建 (预计 3-5 天)
- [ ] 项目目录创建 (`academic_companion/` 骨架)
- [ ] 配置系统 (`config.py` — LLM, Qdrant, 模式预设)
- [ ] RAG 摄入管线 (基于 `rag/pipeline.py`，导入 CS-Base 首批数据)
- [ ] RAG 检索管线验证 (命令行测试 Dense+BM25+Rerank)
- [ ] Qdrant 本地部署验证
- [ ] FastAPI 骨架 (server.py, SSE handler)

### Phase 2: 学习模式 (预计 4-6 天)
- [ ] LearningAgent 封装 (ReActAgent + 系统提示词)
- [ ] RAGRetrievalTool — 将 RetrievalPipeline 注册为 Agent Tool
- [ ] Memory 系统打通:
  - SessionStore 持久化学习进度
  - DevLog 记录学习轨迹
  - Smart Summary 压缩长对话
  - UserModel 构建用户知识状态
- [ ] 上下文工程预设 (学习模式 ContextConfig)
- [ ] Skill 注册 (cs-interview, leetcode-patterns)
- [ ] MCP WebSearchTool (fallback)
- [ ] 命令行端到端测试 → 调优

### Phase 3: 研究模式 (预计 4-6 天)
- [ ] MCP Client 层 + 业务 Tool (arXiv, Semantic Scholar, WebSearch)
- [ ] SearchAgent / FilterAgent (ReAct)
- [ ] AnalyzeAgent (ReflectionAgent + pdf skill + paper-reading skill)
- [ ] SynthesizeAgent (SimpleAgent)
- [ ] ResearchOrchestrator (PlanSolveAgent + TaskTool 子Agent调用)
- [ ] Tool Filter 权限控制测试
- [ ] 命令行端到端测试 → 调优

### Phase 4: WebUI (预计 3-5 天)
- [ ] React + Vite + TypeScript 项目搭建
- [ ] ChatView + SSE 流式集成 (useSSE hook)
- [ ] 消息卡片组件 (markdown + KaTeX + 代码高亮)
- [ ] 工具调用卡片 (折叠展开, 参数/结果展示)
- [ ] 思考过程块 (thinking block)
- [ ] 双模式切换 UI
- [ ] 研究模式多 Agent 流程可视化
- [ ] 样式美化 + 响应式

### Phase 5: 打磨 (预计 2-3 天)
- [ ] Observability 面板 (TraceLogger HTML 可视化)
- [ ] 知识管理后台页面 (RAG索引状态/重建)
- [ ] 演示脚本准备 (5分钟面试演示流程)
- [ ] 文档完善

### Phase 6: 可选增强
- [ ] 语音输入 (框架有 ASR Skill)
- [ ] A2A 协议替代 TaskTool (标准化多Agent通信)
- [ ] 论文引用图谱可视化
- [ ] 学习统计数据仪表盘
- [ ] 更多知识源接入 (Kaggle Technical QA 等)

---

## 10. 备注

- **本文档随着开发推进持续更新**，决策落定后从"已解决"移至正文
- **HelloAgents 框架核心代码不做任何改动**，项目代码完全在 `academic_companion/` 下
- `rag/pipeline.py` 作为基础设施直接复用，增强代码在 `academic_companion/rag_extensions/` 中
- `protocols/` 中 MCP Server 仅作 Client 设计的参考；A2A 和 ANP 按需取用

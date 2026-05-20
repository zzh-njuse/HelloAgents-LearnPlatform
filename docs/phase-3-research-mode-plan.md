# Phase 3: 研究模式 + Memory 集成 — 开发报告

> **SDD (Specification-Driven Development)**
> **状态: 完成 (2026-05-19)**
> 测试: 21 passed, 0 failed (Phase 3 新增)

---

## Context

Phase 1 完成了 RAG/MCP 框架集成，Phase 2 完成了学习模式。Phase 3 实现研究模式——通过 MCP 协议调用学术 API + 多 Agent 协作完成 搜索→筛选→分析→综述 的全流程。同时恢复了原框架被删除的 Memory 子系统（4 种记忆类型），集成到 `hello_agents/memory/`。

### 实际技术栈（与计划有差异）

| 组件 | 计划 | 实际 | 原因 |
|------|------|------|------|
| MCP 连接 | stdio transport | **内存 transport**（FastMCP 实例直连） | arxiv-search-mcp-server 的 `__main__.py` 有 import bug；内存 transport 更可靠 |
| S2 限流 | 直接可用 | **需要 API key**，否则共享 1000 req/s 全局限流 | Semantic Scholar 未认证用户限流极严 |
| arXiv 限流 | 直接可用 | **IP 级 429**，日配额耗尽 | 测试密集调用触发；生产场景 S2 主力 + arXiv 补充 |
| Orchestrator | PlanSolveAgent.Executor | **自定义 run()**，TaskTool 委派子 Agent | Executor 不支持 TaskTool，上下文无隔离 |
| Memory | 计划内无 | **完整 4 种记忆类型**（Working/Episodic/Semantic/Perceptual） | 用户找到原框架删除的 hello_memory 代码 |

---

## 实际产出

```
academic_companion/
├── mcp_extensions/              # ★ 新建
│   ├── __init__.py
│   ├── base.py                  # McpToolBase (sync/async 桥接 + 内存 transport)
│   ├── arxiv_tool.py            # ArxivSearchTool (MCP 协议, rate limiter)
│   └── semantic_scholar_tool.py # SemanticScholarTool (MCP 协议, rate limiter)
├── memory_extensions/
│   └── research_notes.py        # ★ 新建 — ResearchNotes + PaperEntry (ID 去重 + Qdrant)
├── agents/research/             # ★ 新建 (原为空目录)
│   ├── __init__.py
│   ├── search_agent.py          # SearchAgent (ReActAgent + ArxivSearch + SemanticScholar)
│   ├── filter_agent.py          # FilterAgent (ReActAgent + RAGRetrieval)
│   ├── analyze_agent.py         # AnalyzeAgent (ReflectionAgent + paper-reading Skill)
│   ├── synthesize_agent.py      # SynthesizeAgent (SimpleAgent + WriteTool)
│   └── orchestrator.py          # ResearchOrchestrator (Plan+TaskTool 多 Agent 编排)
├── demo_research.py             # ★ 新建 — CLI 端到端 Demo (4 场景)
tests/
├── test_mcp_tools.py            # ★ 新建 — 8 tests
└── test_research_notes.py       # ★ 新建 — 13 tests

hello_agents/memory/             # ★ 新建 — 从 hello_memory 迁移
├── __init__.py                  # 导出 MemoryManager + 4 种记忆类型
├── base.py                      # MemoryItem, MemoryConfig, BaseMemory
├── manager.py                   # 统一入口 (add/retrieve/forget/consolidate)
├── storage/
│   ├── document_store.py        # SQLite 文档存储
│   └── neo4j_store.py           # Neo4j 图存储
└── types/
    ├── working.py               # 短期工作记忆 (TF-IDF + 时间衰减)
    ├── episodic.py              # 情景记忆 (SQLite + Qdrant，含模式识别)
    ├── semantic.py              # 语义记忆 (Qdrant + Neo4j + spaCy)
    └── perceptual.py            # 感知记忆 (多模态向量存储)
```

### 删除的冗余

| 删除 | 原因 |
|------|------|
| `hello_memory/` 整个目录 | 已迁移到 `hello_agents/memory/` |
| `hello_agents/memory/storage/qdrant_store.py` | 用 `hello_agents/storage/qdrant_store.py` 替代 |
| `hello_memory/memory/rag/` | 已由 Phase 1 集成到 `hello_agents/rag/` |
| `hello_memory/memory/embedding.py` | 用 `hello_agents/embedding/` 替代 |

---

## Demo 端到端验证

### 场景 1: MCP 工具 ✅
```
ArxivSearch MCP: OK
SemanticScholar MCP: OK
arXiv 搜索: success — 9323 chars (含 rate limiter)
SemanticScholar 搜索: success — 14378 chars (API key 生效)
```

### 场景 2: ResearchNotes 去重 ✅
```
去重结果: 新论文 1 篇, 已有记录 1 篇
语义搜索: 正常
```

### 场景 3: SearchAgent 真实搜索 ✅
Agent 通过 Semantic Scholar MCP 搜到 5 篇真实论文，结构化输出含标题/作者/venue/引用/摘要/对比表：

| 论文 | 出处 | 引用 |
|------|------|------|
| RepairAgent: LLM-Based Agent for Program Repair | ICSE 2024 | 312 |
| ReinFix: Repair Ingredients Search | arXiv 2025 | 8 |
| PEFT on APR | ASE 2024 | 14 |
| Agent-Based APR (Multi-Agent + Static Analysis) | IEEE Access 2026 | 0 |
| RGFL: Reasoning Guided Fault Localization | arXiv 2026 | 1 |

### 场景 4: 多 Agent 编排 ⚠️
Plan + TaskTool 委派流程跑通，子 Agent 正确调用了 MCP 工具。但长链执行中模型 steering 不够稳定——搜索/分析正常，上下文传递在复杂场景下仍需优化。

---

## 遇到的问题与解决方案

### 问题 1: arxiv-search-mcp-server 的 `__main__.py` 有 import bug

**现象**: `python -m arxiv_search_mcp_server` 报 `ModuleNotFoundError: No module named 'arxiv_search_mcp'`

**根因**: 包的 `__main__.py` 写了 `from arxiv_search_mcp.server import main`，少写了 `_server` 后缀

**解决**: 改为内存 transport——直接获取 `arxiv_search_mcp_server.server.mcp`（FastMCP 实例），传给 MCPClient。免子进程开销，协议不变。

---

### 问题 2: Windows GBK 编码——emoji print 崩溃

**现象**: MCP 工具调用时报 `'gbk' codec can't encode character '\U0001f9e0'`

**根因**: `MCPClient.__aenter__` 和 `ToolRegistry.register_tool` 中有 emoji 字符的 `print()`。Windows 中文环境默认 GBK 编码无法输出 emoji。

**解决**（4 处）:
- `mcp/client.py`: 删除 `__aenter__`/`__aexit__` 中的 emoji print
- `tools/registry.py`: 替换 3 处 emoji print 为纯 ASCII

---

### 问题 3: deepseek-v4-flash 不支持强制 tool_choice

**现象**: PlanSolveAgent 的 Planner 返回 `deepseek-reasoner does not support this tool_choice`

**根因**: `deepseek-v4-flash` 被 DeepSeek API 归类为 reasoner 模型。reasoner 模型（含 o1/o3）不支持 `tool_choice={"type": "function", "function": {"name": "..."}}` 这种强制指定。但它们支持 `tool_choice="auto"`。

**验证**:
```
tool_choice="auto"                          → ✅ 模型正常调 generate_plan
tool_choice={"type": "function", ...}       → ❌ API 拒绝
tool_choice="required"                      → ❌ 同样被拒（reasoner 不接受任何强制）
```

**解决**（2 层）:
1. `llm_adapters.py`: `dict → "required" → "auto"` 三阶段 cascade，自动降级到模型可接受的值
2. `plan_solve_agent.py`: 强化 Planner 的 system prompt——"必须调用 generate_plan 函数，不要用文字回复"

两层协作：适配器保证 API 不崩溃，Planner 提示词保证 auto 模式下模型仍调对函数。

---

### 问题 4: reasoning_content 未回传（3 处遗漏）

**现象**: Phase 2 修了 ReActAgent，但 PlanSolveAgent 的 Executor、ReflectionAgent、SimpleAgent 的函数调用循环仍有同样问题——第二轮 API 调用报 `reasoning_content must be passed back`

**根因**: Phase 2 的修复只覆盖了 `ReActAgent._step()`。PlanSolveAgent 的 `Executor._execute_step()`、`ReflectionAgent._get_llm_response()`、`SimpleAgent.run()` 都有自己独立的函数调用循环，构建 assistant 消息时未包含 `reasoning_content`。

**解决**（3 处）:
| 文件 | 位置 | 修复 |
|------|------|------|
| `plan_solve_agent.py` | `Executor._execute_step()` 构建 assistant 消息 | `if response.reasoning_content: assistant_msg["reasoning_content"] = ...` |
| `reflection_agent.py` | `_get_llm_response()` 构建 assistant 消息 | 同上 |
| `simple_agent.py` | `run()` 构建 assistant 消息 | 同上 |

---

### 问题 5: 子 Agent 没有 MCP 工具权限

**现象**: SearchAgent 作为子 Agent 运行时提示"只看到 Thought 和 Finish 两个工具"

**根因**: `ReadOnlyFilter` 的白名单只有 `Read/Glob/Grep/Skill`，不包含 `ArxivSearch`/`SemanticScholar`。ToolFilter 把 MCP 工具全过滤掉了。

**解决**: `orchestrator.py` 中定义 `RESEARCH_READONLY` 和 `RESEARCH_FULL` 两个 `CustomFilter`：
- 搜索/筛选/分析步: 允许 ArxivSearch + SemanticScholar + RAGRetrieval + Skill + Read/Glob/Grep
- 合成步: 黑名单模式，只禁 Bash/Terminal/Execute

---

### 问题 6: Semantic Scholar API 无 key 时限流

**现象**: 多次调用后全部返回 `RateLimitError (429)`，`retry_after: 60`

**根因**: 未认证用户共享 1000 req/s 全局限流。尤其是多场景连续测试时消耗极快。

**解决**:
1. 用户申请免费 API key（[semanticscholar.org/product/api](https://www.semanticscholar.org/product/api)），配额从共享变独享
2. `ArxivSearchTool` 和 `SemanticScholarTool` 各加 rate limiter（3.5s / 2s 最小间隔）
3. 工具 description 提示 LLM "一次给出全面搜索词"

---

### 问题 7: PlanSolveAgent Executor 不走 TaskTool

**现象**: Orchestrator 虽然注册了 TaskTool，但 PlanSolveAgent 的 Executor 自己直接调 `invoke_with_tools`，完全不通过 TaskTool 委派子 Agent。

**根因**: `Executor._execute_step()` 内建了工具调用循环。TaskTool 只是注册在工具列表中的一个普通工具，Executor 和 LLM 都不知道应该用它来委派子 Agent。

**解决**: 重写 `ResearchOrchestrator.run()`——Plan 阶段复用 `Planner.plan()`，Execute 阶段不走 `Executor.execute()`，改为遍历 plan 的每一步，自己调用 `TaskTool.agent_factory()` 创建子 Agent，再 `sub.run_as_subagent(task, tool_filter)`。核心改动 ~40 行。

---

### 问题 8: Memory 迁移中的接口适配（5 处）

hello_memory 与 hello_agents 有 3 个共享模块（embedding / qdrant_store / rag），迁移时需统一。

| # | 差异 | 修复 |
|---|------|------|
| 1 | `QdrantConnectionManager.get_instance()` 不存在 | 在 hello_agents 的 QdrantConnectionManager 添加 `get_instance()` 类方法 |
| 2 | memory 类型用 `QdrantConnectionManager` 做向量搜索 | 改为用 `QdrantVectorStore`（后者有 `search_similar`） |
| 3 | Qdrant Cloud 拒绝 `where={"memory_type": "..."}` filter | 去掉 where filter，改应用层过滤 |
| 4 | embedding 返回 list vs numpy array（`.tolist()` 兼容） | 加 `hasattr(vec, 'tolist')` 检查 |
| 5 | `SemanticMemory._init_databases` 任一失败连累另一个 | 拆成独立 try/except |

---

## 框架代码修改摘要

| 文件 | 改动 | 原因 |
|------|------|------|
| `hello_agents/mcp/client.py` | 删除 emoji print | Windows GBK 兼容 |
| `hello_agents/tools/registry.py` | 替换 3 处 emoji print | Windows GBK 兼容 |
| `hello_agents/core/llm_adapters.py` | `invoke_with_tools`: dict→required→auto 三阶段 cascade | reasoner 模型不支持强制 tool_choice |
| `hello_agents/agents/plan_solve_agent.py` | Planner 强化提示词 + Executor 补 reasoning_content | tool_choice 兼容 + thinking model 回传 |
| `hello_agents/agents/reflection_agent.py` | 构建 assistant 消息时补 reasoning_content | thinking model 回传 |
| `hello_agents/agents/simple_agent.py` | 同上 | thinking model 回传 |
| `hello_agents/storage/qdrant_store.py` | 添加 `get_instance()` + timeout | memory 模块兼容 + 防连接卡死 |
| `hello_agents/context/builder.py` | 更新文档说明 Memory+RAG 注入方式 | GSSC 集成指南 |
| `hello_agents/__init__.py` | 添加 `get_memory_manager()` | memory 延迟导入 |

---

## 小问题记录（调试中遇到的非阻断性问题）

以下问题在调试过程中逐一发现并修复，未在主问题列表中单独列出：

| # | 问题 | 修复 |
|---|------|------|
| 10 | `semantic-scholar-mcp` 要求在调用工具前先 `initialize_server()` | SemanticScholarTool 加 `_ensure_initialized()` 前置调用 |
| 11 | `arxiv-search-mcp-server` MCP 工具参数名是 `terms` 非 `query`，无 `sort_by` | 更新 ArxivSearchTool 参数映射 |
| 12 | Orchestrator 长链执行中 Agent 上下文累积膨胀，模型偏离任务（调 Read/Write 操作 `/tmp/`） | 重写 Orchestrator 为 Plan + TaskTool 委派模式，子 Agent 上下文隔离 |
| 13 | Orchestrator 步骤间上下文传递断裂：`run_as_subagent` 返回的 summary 把搜索结果截断 | 已识别为 GSSC 待办项，当前将前步 summary 拼接为下一步 context |
| 14 | MemoryManager 跨 session SQLite 回读缺失：降级检索只查 `self.episodes`（内存），新 session 为空 | 降级路径加 `doc_store.search_memories()` SQLite 加载 |
| 15 | `QdrantConnectionManager.get_instance()` 不存在于 hello_agents 版本 | 添加 `get_instance()` 类方法兼容 |
| 16 | semantic.py 中 Qdrant 初始化失败连累 Neo4j（同 try 块） | 拆为独立 try/except |
| 17 | WorkingMemory `heapq.heappush` 优先级相同时比较 `MemoryItem` 对象（不支持 `<`） | 加自增计数器 tiebreaker |
| 18 | SemanticMemory Qdrant 写入失败时 `self.semantic_memories.append` 未执行（在 try 块内） | 移到 try 外 + except 内也 append |
| 19 | SemanticMemory `retrieve()` 空结果时直接 `return result_memories[:limit]` 不触发降级 | `return` 改为条件判断 `if result_memories:` |
| 20 | `.gitignore` 中 `memory/` 规则误伤 `hello_agents/memory/` 源码目录 | 改为 `/memory/` + `/memory_data/` 锚定根目录 |
| 21 | QdrantCloud 旧 collection 污染（dim 1 残留），`ensure_collection` 异常处理过宽吞掉维度读取失败 | 紧异常处理 + 维度不匹配时删除重建 + `UnexpectedResponse` 单独处理 |
| 22 | `qdrant_client 1.18.0` 的 `query_points` 不支持 `NamedVector` 查询格式，QdrantCloud 自动开启 multi-vector | 回退为 plain vector 模式 + 重建 collection |
| 23 | Demo 全场景串行执行 → 速率限制累积（S2 + arXiv 交替 429） | S2 申请 API key + 两工具各加 rate limiter + tool description 提示 LLM 合并查询 |
| 24 | `deepseek-v4-flash` 的 `reasoning_content` 必须在每轮对话中回传，漏传则 API 拒绝 | Phase 2 修了 ReActAgent，Phase 3 补修 PlanSolveAgent.Executor / ReflectionAgent / SimpleAgent |

---

## 测试结果

### Phase 3 新增测试
```
tests/test_mcp_tools.py — 8 passed
tests/test_research_notes.py — 13 passed
Total: 21 passed, 0 failed
```

### 数据库连接验证
| 数据库 | 状态 |
|--------|------|
| Qdrant Cloud | ⚠️ 间歇不稳定（中国→AWS us-west），记忆系统已加降级路径 |
| Neo4j Aura | ✅ |
| SQLite (文档存储) | ✅ |

---

## 本日补充 (2026-05-19)

### Memory 系统集成

从原框架删除的 hello_memory 代码中恢复了完整 4 种记忆类型，迁移到 `hello_agents/memory/`：

- **WorkingMemory**: 短期工作记忆，TF-IDF + 时间衰减，纯内存
- **EpisodicMemory**: 情景记忆，SQLite(权威) + Qdrant(向量) 双存储
- **SemanticMemory**: 语义记忆，Qdrant + Neo4j 图存储
- **PerceptualMemory**: 感知记忆，多模态（暂未启用）

### Phase 2 LearningAgent 改造

- LearningAgent 接入 `MemoryManager`，替换 DevLogTool
- `_record_learning()` 双写 UserModel + MemoryManager (Episodic + Semantic)
- System prompt 增加 MemoryManager 检索上下文注入
- UserModel 保留，负责掌握度追踪 + 间隔重复

### Memory 系统问题修复（9 处）

| # | 问题 | 修复 |
|---|------|------|
| 1 | heapq `MemoryItem` 比较冲突 | 加自增计数器 tiebreaker |
| 2 | `encode()` 字符串被拆为字符逐字编码 | `isinstance(texts, str)` → 包装为列表 |
| 3 | semantic `add()` 内存 append 在 try 内，Qdrant 失败后丢失 | 移到 try 外 + except 内也 append |
| 4 | semantic `retrieve()` 空结果不触发降级 | `return` 改为条件 `if result_memories:` |
| 5 | episodic 跨 session SQLite 回读缺失 | 降级路径加 SQLite 加载逻辑 |
| 6 | QdrantCloud 维度不匹配 (dim 1 vs 1024) | `ensure_collection` 紧异常处理 + 维度检查 |
| 7 | QdrantCloud 400/404/409 轮转 | episodic/semantic 各加降级路径 |
| 8 | `add_vectors` 参数名 `metadata` → `metadatas` | 适配 hello_agents 接口 |
| 9 | Emoji GBK 编码（2 处） | mcp/client.py + tools/registry.py |

### 嵌入模型修复

- `hello_agents/embedding/local.py`: `embed()` 方法接受字符串时包装为列表，不再逐字符编码

---

## 后续待办

- [x] **Qdrant 本地部署**: 中国→AWS us-west 网络不稳定，切换为 Docker 本地 Qdrant ✅ — Docker Desktop + D 盘存储, 393MB
- [x] Orchestrator 长链执行稳定性优化（上下文组装 GSSC 集成）✅ — PipelineContext 结构化组装 + 四子 Agent JSON Schema + 降级保障
- [x] LeetCode 全量 2913 题摄入（Phase 2 遗留）✅ — 已摄入到本地 Qdrant, 2913 points
- [x] Phase 2 掌握度评估：从长度占位逻辑改为 LLM 评估 ✅ — CSAssessor + AlgorithmAssessor
- [ ] Phase 2 多模态/图片支持
- [ ] WebUI 前端（Phase 4）
- [ ] A2A 协议替代 TaskTool（加分项）
- [ ] 本地 spaCy 模型安装 (减少 SemanticMemory WARNING)
- [ ] Neo4j `learning_memory` 数据库创建

---

## 2026-05-20/21 实现详情

### 1. Qdrant 本地部署

```bash
docker run -d --name qdrant-local -p 6333:6333 -v D:/qdrant_data:/qdrant/storage qdrant/qdrant:latest
```

**遇到的坑**:

**Docker 代理**: Desktop 配了代理 `192.168.101.8:7890` (不可达), `docker pull` 失败。
→ Settings → Resources → Proxies → 关闭 Manual proxy。

**Python httpx 走代理连 localhost 报 503**: 系统环境变量 `HTTP_PROXY` 导致 httpx 把 localhost 请求发到代理。
curl 不受影响 (不读环境变量代理)。
**修复**: `qdrant_store.py` 连接 localhost 时自动 `os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,.local")`;
`learning_session.py` 启动时同样处理。

**Windows 文件系统警告**: Qdrant 日志 `Unrecognized filesystem` (NTFS 经 Docker Desktop 虚拟化暴露给 Linux)。
实际不影响使用, 数据完好。

**C 盘空间**: Docker Desktop WSL VM ~4.3GB (不可删), HuggingFace 缓存 ~4GB (可删, 模型已在 ModelScope 缓存),
ModelScope 缓存 ~1.3GB (不可删)。清理: `rm -rf ~/.cache/huggingface/`。

### 2. 全量数据摄入

**规模**: CS-Base 880 chunks + LeetCode 2913 chunks = 3793 向量 (1024 维)。
**存储**: D:/qdrant_data, 393MB。

**摄入过程中的 bug** (详见 Phase 2 文档):
- `_chunk_paragraphs` 死循环 (超大段落 + overlap 重建导致 i 不前进)
- torch 2.5.1 → 2.12.0 (CVE-2025-32434 安全限制)
- 僵尸 Python 进程占 20GB → MemoryError
- `add_vectors` 无返回值 / 未传 collection_name / 参数名不匹配
- Qdrant Point ID 必须 UUID (不接受字符串)
- `del chunks` 后引用导致 UnboundLocalError

### 3. Orchestrator 结构化上下文组装

**为什么不用 GSSC**: GSSC 的 Select 阶段 (关键词检索+筛选) 适用于异构信息源。
研究流水线是线性的 — Orchestrator 掌握全部数据, 不缺"搜索", 缺的是"从散文提取结构化字段"。

**改造方案**:

**四种子 Agent 结构化输出 Schema**:

| Agent | 核心字段 |
|-------|---------|
| SearchAgent | `papers: [{title, arxiv_id, authors, year, citations, abstract}]`, `search_queries`, `total_found` |
| FilterAgent | `selected: [{paper_title, arxiv_id, reason, priority}]`, `rejected`, `selection_criteria` |
| AnalyzeAgent | `analysis: {method, experiments, contributions, limitations, key_insight}`, `relevance_rating`, `reproducibility` |
| SynthesizeAgent | `report_markdown`, `comparison_table`, `bibtex`, `key_findings`, `research_gaps` |

**输出方式**: 每个 Agent 的 system prompt 末尾加结构化 JSON 输出要求。
Orchestrator 用 `_parse_structured_output(raw_text)` 提取 JSON 块 (` ```json ``` 或裸 `{...}`)。

**降级保障**: JSON 解析失败 → `{"raw": raw_text, "parse_failed": True}` → 后续步骤退化为原文截断, **不阻塞流水线**。

**PipelineContext** (新建, ~100 行): 按步骤类型选择性格式化前序结果。
- `search` 步骤: 仅 Plan
- `filter` 步骤: Plan + 论文表格 (| # | 标题 | 作者 | 年份 | 引用 |)
- `analyze` 步骤: Plan + 筛选决策表 + 选中论文详情 (含摘要)
- `synthesize` 步骤: Plan + 全部前序步骤摘要卡片

**Token 预算**: max_tokens=6000, 超预算时从最旧的论文详情开始裁剪。

**测试结果**: 4 步骤 token 用量 121-345, 远低于 6000 预算。前序结果完整保留, 无 `r[:500]` 硬截断。

**影响文件**:
- `pipeline_context.py`: **新建** — PipelineContext 组装器
- `orchestrator.py`: Phase 2 替换 `r[:500]` 截断 → PipelineContext + JSON 解析
- `search_agent.py`, `filter_agent.py`, `analyze_agent.py`, `synthesize_agent.py`: system prompt 加结构化输出要求
- `filter_agent.py`: `research_summary=""` → 实际从 ResearchNotes 读取

**附带修复**: `filter_agent.py` 的 `research_summary` 从空字符串改为实际值;
`orchestrator.py` 工厂函数给 FilterAgent 传 `research_notes`。

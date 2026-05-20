# Phase 2: 数据基础 + 学习模式 — 开发报告

> **SDD (Specification-Driven Development)**
> **状态: 完成 (2026-05-16)**
> 测试: 196 passed, 0 failed

---

## Context

Phase 1 已将 RAG pipeline、MCP、Embedding、Storage 集成进 `hello_agents/` 框架。Phase 2 在此基础上构建"学习模式"——Agent 从 Qdrant 知识库检索 CS 八股和 LeetCode 题解，结合用户记忆给出个性化讲解。

### 实际技术栈（与计划有差异）

| 组件 | 计划 | 实际 | 原因 |
|------|------|------|------|
| Embedding 模型 | OpenAI text-embedding-3-small | **本地 bge-large-zh-v1.5** (via ModelScope) | DeepSeek API 不支持 embedding；本地中文效果更好 |
| Qdrant | Qdrant Cloud | Qdrant Cloud (AWS us-west) | 按计划 |
| 模型下载 | HF 直连 | **ModelScope 下载** → 本地路径加载 | HF 从国内下载 1.3GB 太慢 |
| MarkItDown | 使用 pipeline 内置 | **绕过**，直接读 md 文件 | `load_and_chunk_texts` 的 MarkItDown 处理 123 个文件卡死 |

---

## 实际产出

```
academic_companion/
├── __init__.py
├── config.py                     # AcademicConfig + RAGConfig + LearningModeConfig + MemoryConfig
├── run_ingestion.py              # 数据摄入脚本（使用本地 bge）
├── demo_learning.py              # CLI 端到端 Demo
├── agents/
│   ├── __init__.py
│   └── learning_agent.py         # LearningAgent (ReActAgent + RAG + Skills + Memory)
├── rag_extensions/
│   ├── __init__.py
│   ├── loaders.py                # CS-Base + LeetCode 数据加载器
│   └── rag_tool.py               # RAGRetrievalTool (Agent 可调用的检索工具)
├── memory_extensions/
│   ├── __init__.py
│   └── user_model.py             # UserModel (知识状态图 + 间隔重复)
├── skills/
│   ├── __init__.py
│   ├── cs-interview/SKILL.md     # CS 面试方法论
│   ├── leetcode-patterns/SKILL.md # 算法解题模式
│   └── paper-reading/SKILL.md    # 三段式论文阅读法
├── tools/
│   ├── __init__.py
│   └── web_search_fallback.py    # MCP WebSearch fallback
└── api/
    └── __init__.py               # (Phase 4 填充)
```

### 数据摄入结果

| Collection | 源 | 数据量 | Qdrant 中 chunks |
|-----------|------|--------|-----------------|
| `cs_fundamentals` | CS-Base (xiaolincoding) | 123 个 .md 文件 | **~2185** |
| `leetcode` | neenza/leetcode-problems | 500/2913 题 | **~460** |

### RAG 检索验证

| 查询 | Collection | Top-1 评分 | 结果 |
|------|-----------|-----------|------|
| "TCP三次握手 拥塞控制" | cs_fundamentals | 0.719 | tcp_no_accpet.md 等 5 篇 |
| "Two Sum 两数之和" | leetcode | 0.655 | Sum of Two Integers 等 3 题 |

---

## 遇到的问题与解决方案

### 问题 1: GitHub 无法直连，知识数据下载失败

**现象**: `git clone https://github.com/...` 多次超时（Connection timed out）

**解决**: 用户手动 clone 两个仓库到 `data/cs_fundamentals/` 和 `data/leetcode/`

---

### 问题 2: HuggingFace 下载 bge 模型极慢

**现象**: bge-large-zh-v1.5 (1.3GB) 从 HF 直连下载 5 分钟无任何输出

**尝试**:
1. HF 镜像 (`hf-mirror.com`) — MiniLM 秒下，但对 bge 1.3GB 仍然慢
2. 换用 MiniLM (80MB) — 快但中文精度不够

**最终方案**: 用户通过 ModelScope CLI 下载 bge 到本地缓存 (`C:/Users/Admin/.cache/modelscope/hub/models/BAAI/bge-large-zh-v1___5`)，摄入脚本指向本地路径加载模型，1 秒完成

---

### 问题 3: `load_and_chunk_texts` 处理 MarkDown 文件极慢

**现象**: pipeline 内置的 `load_and_chunk_texts()` 对 123 个 .md 文件调 MarkItDown 转换，5+ 分钟无进展

**根因**: MarkItDown 对每个文件都要导入、检测格式、转换，即使纯 .md 文件也走完整流程

**解决**: 绕过 pipeline，直接 `fp.read_text(encoding='utf-8')` 读文件，按 `\n\n` 段落切分。123 个文件 < 1 分钟处理完成，生成 2225 chunks

---

### 问题 4: Qdrant Cloud 点 ID 格式限制

**现象**: LeetCode 摄入时 `lc-41` 报错 "not a valid point ID"，纯整数 `1` 也报同样错误

**根因**: Qdrant Cloud 要求 point ID 为 unsigned integer 或 UUID，不接受任意字符串

**解决**: 使用 `uuid.uuid5()` 生成确定性 UUID（`uuid.uuid5(NAMESPACE_DNS, f'leetcode-{pid}')`）

---

### 问题 5: Qdrant Cloud 上传超时

**现象**: `store.add_vectors()` 批量上传时出现 `ReadTimeout`，500 条中有 ~40 条丢失

**根因**: Qdrant Cloud 免费 tier 存在速率限制，大批量上传触发超时

**解决**: 将 batch_size 从 50 降为 20，加 3 重试 + 3 秒间隔。丢失率从 10% 降至 <2%

---

### 问题 6: pipeline 接口与新版依赖不兼容（6 处）

**现象**: RAG 检索管线调用时报错，无法使用 `create_rag_pipeline()` 和 `search_vectors_expanded()`

**修复清单**:

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `factory.py` | `get_dimension()` 不接受参数，但 pipeline 调用 `get_dimension(384)` | 加 `default` 参数 + try/except |
| 2 | `qdrant_store.py` | `QdrantVectorStore.__init__` 不接 `url`/`api_key` 等参数 | 添加可选参数 |
| 3 | `qdrant_store.py` | `QdrantConnectionManager.__new__` 不接参数 | 添加 `**kwargs` 兼容 |
| 4 | `qdrant_store.py` | `search_similar` 参数名 `top_k` vs pipeline 用 `limit` | 添加 `limit`/`where` 别名 |
| 5 | `qdrant_store.py` | `client.search()` 不存在（新版 qdrant-client 改名） | 改为 `client.query_points()` |
| 6 | `qdrant_store.py` | `query_points` 参数名 `query` vs `query_vector` | 改为 `query`；返回 `.points` 迭代 |
| 7 | `local.py` | pipeline 调 `embedder.encode()` 但我们的方法叫 `embed()` | 添加 `encode()` -> `embed()` 别名 |

**根因**: 原始 `rag/pipeline.py` 依赖的是旧版 qdrant-client API (`search`/`query_vector`) + 原始的 embedding/storage 接口，我们在 Phase 1 重构时未完全对齐

---

### 问题 7: 测试预置问题（6 个）

Phase 1 修复了 5 个预置测试，Phase 2 修复了 1 个（`get_dimension` 参数签名）。详见 Phase 1 报告。

---

## 接口兼容性摘要

Phase 2 中 `hello_agents/` 框架代码实际行的修改：

| 文件 | 改动 | 原因 |
|------|------|------|
| `embedding/factory.py` | `get_dimension()` 加 `default` 参数 | 兼容 `pipeline.py` 调用 |
| `embedding/local.py` | 添加 `encode()` 方法 | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `__init__` 接受 `url`/`api_key` | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `__new__` 接受 `url`/`api_key` | 单例模式兼容 |
| `storage/qdrant_store.py` | `search_similar` 加 `limit`/`where` 别名 | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `client.search` → `client.query_points` | 新版 qdrant-client API |
| `storage/qdrant_store.py` | `query_vector` → `query` | 新版 qdrant-client API |

---

## 问题 8: RAG 检索发送无效 filter 字段（Qdrant Cloud 严格校验）

**现象**: RAG Tool 检索时报 4 个 validation errors — `filter.memory_type`, `filter.is_rag_data`, `filter.data_source`, `filter.rag_namespace` 均为 "Extra inputs are not permitted"

**根因**: pipeline 的 `search_vectors` 硬编码了旧版 payload filter 字段（`memory_type: "rag_chunk"` 等），这些字段在我们新版数据摄入时并未写入 payload，且新版 Qdrant Cloud 开启严格校验后拒绝未声明的字段

**解决**: 重写 `RAGRetrievalTool` 的检索逻辑，绕开 pipeline 的 `search_vectors_expanded`，直接使用 `QdrantVectorStore.search_similar()` 进行查询，不添加任何 filter

> **Phase 3 补充** (2026-05-19): Memory 子系统迁移时遇到同一问题——EpisodicMemory 和 SemanticMemory 的 where filter 含未声明字段 `memory_type`。修复方式相同：去掉 Qdrant 层 filter，改应用层过滤。

---

## 问题 9: Thinking Model 的 `reasoning_content` 未回传

**现象**: DeepSeek 报错 `The reasoning_content in the thinking mode must be passed back to the API`，导致 Function Calling 第二轮调用失败

**根因**: 
1. `LLMToolResponse` 没有 `reasoning_content` 字段
2. OpenAI 适配器 `invoke_with_tools` 未提取 `reasoning_content`
3. `react_agent.py` 构建 assistant 消息时未包含 `reasoning_content`

**解决**（3 处改动）:
- `llm_response.py`: `LLMToolResponse` 添加 `reasoning_content: Optional[str] = None`
- `llm_adapters.py`: `OpenAIAdapter.invoke_with_tools` 提取 `message.reasoning_content`
- `react_agent.py`: assistant 消息字典中条件性添加 `reasoning_content`

> **Phase 3 补充** (2026-05-19): 此问题只修了 ReActAgent，PlanSolveAgent.Executor、ReflectionAgent、SimpleAgent 的函数调用循环有同样遗漏。Phase 3 补修了 3 处：`plan_solve_agent.py`、`reflection_agent.py`、`simple_agent.py` 中构建 assistant 消息的逻辑。

---

## 问题 10: TraceLogger finalize 后无法复用

**现象**: 第二个 `agent.run()` 抛出 `ValueError: I/O operation on closed file`

**根因**: `_run_impl()` 末尾调用 `trace_logger.finalize()` 关闭了 JSONL 和 HTML 文件，但 trace_logger 实例在整个 Agent 生命周期中是同一个，第二次 run 试图写已关闭的文件

**解决**: 在 `TraceLogger.log_event()` 开头检测 `_finalized` 标志，如已 finalized 则重新打开文件（append 模式）；同时在 `finalize()` 中设置标志

---

## 问题 11: SkillLoader 被父类 Agent.__init__ 覆盖为 None

**现象**: `agent.skill_loader.list_skills()` 报 `'NoneType' object has no attribute 'list_skills'`

**根因**: 父类 `Agent.__init__` 第 93 行 `self.skill_loader = None` 覆盖了子类在 `super().__init__()` 前设置的值。子类设了 `skills_enabled=False` 阻止父类重建

**解决**: 将 `SkillLoader` 创建和 `SkillTool` 注册移到 `super().__init__()` 之后执行

---

## 问题 12: 数据摄入时 MarkItDown 瓶颈 & Qdrant ID 限制 & 超时

详见问题 3-5（已在摄入阶段修复）。

---

## 接口兼容性摘要

Phase 2 中 `hello_agents/` 框架代码实际行的修改：

| 文件 | 改动 | 原因 |
|------|------|------|
| `embedding/factory.py` | `get_dimension()` 加 `default` 参数 | 兼容 `pipeline.py` 调用 |
| `embedding/local.py` | 添加 `encode()` 方法 | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `__init__` 接受 `url`/`api_key` | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `__new__` 接受 `url`/`api_key` | 单例模式兼容 |
| `storage/qdrant_store.py` | `search_similar` 加 `limit`/`where` 别名 | 兼容 `pipeline.py` 调用 |
| `storage/qdrant_store.py` | `client.search` → `client.query_points` | 新版 qdrant-client API |
| `storage/qdrant_store.py` | `query_vector` → `query` | 新版 qdrant-client API |
| `llm_response.py` | `LLMToolResponse` 加 `reasoning_content` | thinking model 需要回传 |
| `llm_adapters.py` | `invoke_with_tools` 提取 `reasoning_content` | thinking model 需要回传 |
| `react_agent.py` | assistant message 包含 `reasoning_content` | thinking model 需要回传 |
| `observability/trace_logger.py` | `log_event` 自动重开文件；`_finalized` 标志 | 支持多轮 run() |

---

## 测试结果

### 单元测试
```
196 passed, 1 skipped, 0 failed
```

### CLI Demo 端到端验证

```
场景 1: CS 概念讲解 — TCP 拥塞控制      ✅ 通过
  - Agent 自动调用 RAGRetrieval → Skill(cs-interview) → TodoWrite → DevLog
  - 生成完整四步教学: 概念→原理→实例→练习题
  - RAG 检索评分 0.759（高相关性）
  
场景 2: 算法题辅导 — 滑动窗口         ✅ 通过  
  - Agent 加载 leetcode-patterns Skill
  - 自主讲解 LC 424（替换后的最长重复字符）
  - 含代码实现 + 复杂度分析 + 举一反三
  
场景 3: 学习状态检查                  ✅ 通过
  - UserModel 追踪 2 个主题掌握度 (47%, 69%)
  - 给出复习建议（间隔重复算法）
  - memory/user_model.json 持久化正常
```

---

## Phase 3 改造 (2026-05-19)

### Memory 系统集成
- [x] LearningAgent 接入 `MemoryManager`（Working + Episodic + Semantic） ✅
- [x] 替换 DevLogTool 为 EpisodicMemory（每次学习存为 episode） ✅
- [x] UserModel 保留，负责掌握度追踪 + 间隔重复 ✅
- [x] System prompt 增加 MemoryManager 检索结果注入 ✅

### 后续待办

- [x] CLI demo 端到端验证 (`demo_learning.py`) ✅
- [x] **掌握度评估优化**: 当前用 `min(70, 40 + len(answer)/100)` 按回答长度评分的占位逻辑，应接入 LLM 精确评估 ✅ — 已实现 CSAssessor (LLM 出题+评分) + AlgorithmAssessor (LeetCode 匹配)
- [ ] **多模态/图片支持**: RAG 有 ImageDocument 数据模型但无处理逻辑；PerceptualMemory 设计支持多模态但未启用
- [x] LeetCode 全量 2913 题摄入（当前只摄入了 500 题）✅ — 已摄入 2913 题到本地 Qdrant
- [x] bge 模型路径配置化（当前硬编码在 `run_ingestion.py` 中）✅ — 已改为命名注册表 + `.env` 配置
- [x] `run_ingestion.py` 中的直接文本切分替换为 pipeline 的 `_split_paragraphs_with_headings` ✅ — CS-Base 已走 `load_and_chunk_texts`
- [x] Learning Agent 会话化 + GSSC 上下文管线 ✅ — ContextBuilder 四路组装(WorkingMemory+Episodic+Semantic+RAG)，支持多轮对话 + 章节进度
- [x] Qdrant 本地部署 ✅ — Docker Desktop, D 盘存储, 数据 393MB

---

## 2026-05-20/21 实现详情

### 1. BGE 模型路径配置化 + 命名注册表

**改动**: `factory.py` 单例 → 命名注册表，支持多 embedder 共存。

| 调用方式 | 环境变量 | 默认模型 | 维度 | 大小 | 用途 |
|---------|---------|---------|------|------|------|
| `get_text_embedder("rag")` | `EMBED_RAG_MODEL` | bge-large-zh-v1.5 | 1024 | 1.3GB | RAG 摄入+查询 |
| `get_text_embedder("memory")` | `EMBED_MEMORY_MODEL` | bge-small-zh-v1.5 | 512 | 100MB | 记忆系统 |
| `get_text_embedder()` | → `"default"` → `EMBED_RAG_MODEL` | 同 rag | | | 向后兼容 |

**影响文件**: `factory.py`, `semantic.py`, `episodic.py`, `perceptual.py`, `research_notes.py`, `run_ingestion.py`, `.env`

**注意**: bge-small 首次使用时会从 HF 镜像下载 (~100MB)，已配置 `HF_ENDPOINT=https://hf-mirror.com`。

### 2. Learning Agent 会话化 + GSSC 上下文管线

**问题根因**:
- `ReActAgent._build_messages()` 不注入历史 → 每次 run() 空白对话
- WorkingMemory 从未写入 → `_build_memory_context()` 永远返回"暂无历史记忆"
- Episodic/Semantic 只写不读
- `ContextBuilder` (GSSC) 已实现但无人使用

**方案**: 每次 `run()` 前用 `ContextBuilder.build()` 组装四路上下文：
1. **WorkingMemory** → `task_state` — 当前会话近期学习摘要
2. **EpisodicMemory** → `related_memory` — 同章节历史学习事件
3. **SemanticMemory** → `related_memory` — 知识图谱概念关联
4. **RAG** → `retrieval` — 按章节 `source_dir` 过滤的知识库内容

答完后写入 WorkingMemory (importance=0.7, 高于 consolidation_threshold=0.85, 确保不会被立即搬走)。

**影响文件**:
- `learning_agent.py`: 重写 `_build_messages()` + `_build_context()` + `_record_learning()`
- `learning_session.py`: **新建** — 状态机 (IDLE→SELECTING→LEARNING→ASSESSING) + CLI 循环
- `session_demo.py`: **新建** — 入口脚本
- `user_model.py`: +ChapterProgress + _mastery_bar 可视化
- `rag_tool.py`: +source_dir 参数 + Qdrant payload filter

**CLI 命令**: `/select <mode>` `/progress` `/learn <id>` `/stop` `/status` `/help`

**输出整洁化**: `agent.run()` 时 `contextlib.redirect_stdout/stderr` 捕获 ReAct 内部日志
→ 写入 `memory/debug/agent_trace.log` → 用户只看最终回答。
同时抑制 9 个模块的 INFO 日志 + TQDM/HF 进度条。

**已知 bug — WorkingMemory 被立即清空**:
`consolidate_memories(importance_threshold=0.7)` 在每次 `_record_learning()` 后触发。
写入的 working memory 也是 importance=0.7, 刚好等于阈值, 立即被搬走。
**修复**: 阈值提高到 0.85。

### 3. 掌握度评估优化

**方案**: 两种模式分开评测。

**CS 八股** (`/stop` 触发):
1. 收集章节信息 + WorkingMemory 摘要
2. LLM 生成 3 道简答题 (含参考答案)
3. 逐题展示 → 用户输入回答
4. LLM 评估全部回答 → 分数 + 薄弱点 + 评语
5. `UserModel.update_chapter_progress(real_score)`

**算法** (`/stop` 触发):
1. 根据章节 topics 匹配 2-3 道 LeetCode 题 (60% 有题解 + 40% 无题解)
2. 展示题号 + 难度 + leetcode.cn 链接
3. 用户去 LeetCode 完成 → 回报 y/n
4. 通过率 → 掌握度
5. `UserModel.update_chapter_progress(real_score)`

**影响文件**: `assessor.py` (新建), `learning_session.py` (`stop_learning()` 重写)

### 4. 全量数据摄入 — 踩坑记录

**摄入规模**: CS-Base 880 chunks (109 个 md) + LeetCode 2913 chunks = 3793 总向量 (1024 维)。

**坑 1: `_chunk_paragraphs` 死循环**
当段落超 `chunk_tokens`(800) 且 overlap 重建后无法合并时, `i` 不前进 → 无限循环。
测试: `how_to_lock.md` 276 段落 → 死循环产出 9770 微 chunk → 修复后 23 chunks。
**修复两处** (pipeline.py):
1. `p_tokens > chunk_tokens` 时直接强发, 跳过 else 分支
2. overlap 重建后若同一段落仍无法合并, 强制发射 cur 并重置

**坑 2: torch 版本**
torch 2.5.1 太旧, `sentence-transformers` 报 CVE-2025-32434 安全漏洞限制。
**修复**: `pip install torch>=2.6` → 2.12.0 (123MB)

**坑 3: 内存不足**
两个僵尸 Python 进程各占 ~10GB (前次失败摄入残留), 系统只剩 4GB 空闲 → MemoryError。
**修复**: `Stop-Process -Name python -Force` → 释放回 23.7GB。

**坑 4: `add_vectors` API**
- `add_vectors()` 无返回值 (None), 但 `index_chunks()` 检查 `if success:` → 当成失败
- `add_vectors()` 调用未传 `collection_name`, 数据全进默认 `hello_agents_rag_vectors`
- 参数名是 `metadatas` (复数), 调用时写了 `metadata` (单数)
**修复**: 删返回值检查; 传 `collection_name=rag_namespace`; `metadata` → `metadatas`

**坑 5: Qdrant Point ID**
Qdrant 1.18 不接受字符串 ID (如 `lc-1`), 只接受整数或 UUID。
**修复**: `add_vectors()` 中用 `uuid.uuid5(uuid.NAMESPACE_DNS, str(id_))` 转换。

**坑 6: `del chunks` 顺序**
`total_cs_chunks += len(chunks)` 放在 `del chunks` 之后 → `UnboundLocalError`。
**修复**: 先累加, 再 del。

**最终结果**: cs_fundamentals 880 points + leetcode 2913 points, D 盘 393MB。

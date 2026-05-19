# Phase 1: RAG & MCP 集成至 hello_agents 框架

> **SDD (Specification-Driven Development)**
> 本文档既是规格说明，也是开发计划。每个子任务有明确的输入/输出/验收标准。
> **关联系统 Plan**: `C:\Users\Admin\.claude\plans\rag-mcp-hello-agent-sdd-todolist-velvet-willow.md`

---

## Context

### 背景
HelloAgents 框架现有两个独立文件夹 `rag/` 和 `protocols/`，包含原先被删除的 RAG 和 MCP 实现。代码功能完整但脱离框架，存在断裂的导入路径、缺失的依赖模块。需要将它们修缮后正式集成到 `hello_agents/` 包中。

### 目标
- `hello_agents/rag/` — 完整的 RAG 子包（基于原 `rag/` 代码修复）
- `hello_agents/mcp/` — MCP 客户端+服务端子包（基于原 `protocols/mcp/`）
- `hello_agents/embedding/` — Embedding 抽象层（填补缺失依赖）
- `hello_agents/storage/` — Qdrant 向量存储封装（填补缺失依赖）
- 更新 `hello_agents/__init__.py` 导出新模块
- 删除根目录下的 `rag/` 和 `protocols/` 文件夹

### 预期产出
一个 `hello_agents` 包，其中 `rag` 和 `mcp` 子包可以 `from hello_agents.rag import ...` 和 `from hello_agents.mcp import ...` 正常导入使用。

---

## 任务分解

### Task 1: 创建 `hello_agents/embedding/` 子包

**输入**: `rag/__init__.py` 中的导入声明（EmbeddingModel, LocalTransformerEmbedding, TFIDFEmbedding, create_embedding_model, create_embedding_model_with_fallback, get_text_embedder, get_dimension）

**产出**:
```
hello_agents/embedding/
├── __init__.py    # 导出所有类
├── base.py        # EmbeddingModel 抽象基类
├── local.py       # LocalTransformerEmbedding (sentence-transformers)
├── tfidf.py       # TFIDFEmbedding
└── factory.py     # create_embedding_model, create_embedding_model_with_fallback, get_text_embedder, get_dimension
```

**规格**:
- `EmbeddingModel` — 抽象基类，定义 `embed(texts: List[str]) -> List[List[float]]` 和 `dimension` 属性
- `LocalTransformerEmbedding` — 基于 sentence-transformers，支持 `bge-large-zh-v1.5`, `all-MiniLM-L6-v2` 等，带内存缓存
- `TFIDFEmbedding` — 基于 sklearn TfidfVectorizer 的稀疏向量，用于 BM25 混合检索的 fallback
- `create_embedding_model_with_fallback()` — 优先尝试 sentence-transformers，失败则 fallback 到 TFIDF
- `get_text_embedder()` — 全局单例，返回当前活跃的 embedder
- `get_dimension()` — 返回当前 embedder 的维度

**验收**:
- [ ] `from hello_agents.embedding import LocalTransformerEmbedding` 可正常导入
- [ ] `LocalTransformerEmbedding().embed(["测试文本"])` 返回非空向量
- [ ] `create_embedding_model_with_fallback()` 在无 GPU 环境下也能返回可用 embedder

---

### Task 2: 创建 `hello_agents/storage/qdrant_store.py`

**输入**: `rag/pipeline.py` 对 QdrantVectorStore 和 QdrantConnectionManager 的使用方式

**产出**:
```
hello_agents/storage/
├── __init__.py        # 导出 QdrantVectorStore
└── qdrant_store.py    # QdrantVectorStore + QdrantConnectionManager
```

**规格**:
- `QdrantConnectionManager` — 单例模式，管理 Qdrant HTTP 客户端连接，从环境变量 `QDRANT_URL` 和 `QDRANT_API_KEY` 初始化
- `QdrantVectorStore` — 封装 qdrant_client 的 CRUD 操作：
  - `add_vectors(vectors, metadatas, ids, collection_name)` — 批量写入向量+元数据
  - `search_similar(query_vector, top_k, filter_conditions, collection_name)` — 相似搜索
  - `get_collection_stats(collection_name)` — 获取集合统计
  - `ensure_collection(collection_name, dimension, distance)` — 确保集合存在
  - 支持 cosine/dot 两种距离度量

**验收**:
- [ ] 可连接本地 Qdrant 实例（或 memory 模式）
- [ ] `store.add_vectors(...)` + `store.search_similar(...)` 端到端可用
- [ ] 无 Qdrant 服务时给出清晰错误提示而非崩溃

---

### Task 3: 修复并迁移 `rag/` → `hello_agents/rag/`

**输入**: 当前 `rag/` 目录的全部文件

**产出**:
```
hello_agents/rag/
├── __init__.py      # 更新为从 hello_agents 内部导入
├── document.py      # 直接迁移（无框架依赖，不改动）
└── pipeline.py      # 修复导入路径 + 清理无用代码
```

**改动清单**:

| 位置 | 原代码 | 新代码 |
|------|--------|--------|
| `pipeline.py:7` | `from ..embedding import get_text_embedder, get_dimension` | `from hello_agents.embedding import get_text_embedder, get_dimension` |
| `pipeline.py:8` | `from ..storage.qdrant_store import QdrantVectorStore` | `from hello_agents.storage.qdrant_store import QdrantVectorStore` |
| `pipeline.py:467` | `from ..storage.qdrant_store import QdrantConnectionManager` | `from hello_agents.storage.qdrant_store import QdrantConnectionManager` |
| `pipeline.py:714,730,1114` | `from ...core.llm import HelloAgentsLLM` | `from hello_agents.core.llm import HelloAgentsLLM` |
| `pipeline.py:4-6` | 未使用的 `import sqlite3, time, json` | 删除 |
| `pipeline.py:480` | 未使用的 `cache_db` 参数 | 保留参数签名（向后兼容），但标注 `# noqa: ARG001` |
| `rag/__init__.py` | `from ..embedding import ...` (全部删除) | 只从自身 pipeline.py 和 document.py 导出，不再跨包导出 embedding 相关 |

**验收**:
- [ ] `from hello_agents.rag import create_rag_pipeline` 可导入
- [ ] `create_rag_pipeline()` 返回可用的 pipeline 字典
- [ ] `pipeline["add_documents"](["test.md"])` 可完成 ingestion
- [ ] `pipeline["search"]("测试查询")` 返回结果列表

---

### Task 4: 迁移 `protocols/mcp/` → `hello_agents/mcp/`

**输入**: 当前 `protocols/mcp/` 全部文件

**产出**:
```
hello_agents/mcp/
├── __init__.py    # 更新导入路径，导出 MCPClient, MCPServer, create_context, parse_context
├── client.py      # 直接迁移（仅依赖外部 fastmcp，无框架内部依赖）
├── server.py      # 直接迁移
└── utils.py       # 直接迁移（无外部依赖）
```

**改动清单**:
- `client.py`: 无需改动（只依赖外部 `fastmcp` 库）
- `server.py`: 无需改动（只依赖外部 `fastmcp` 库）
- `utils.py`: 无需改动（无外部依赖）
- `__init__.py`: 更新内部相对导入路径

**验收**:
- [ ] `from hello_agents.mcp import MCPClient, MCPServer` 可导入（即使 fastmcp 未安装也有友好提示）
- [ ] `from hello_agents.mcp import create_context, parse_context` 可直接使用（无需 fastmcp）
- [ ] MCPServer 示例代码可运行（需 fastmcp 已安装）

---

### Task 5: 更新 `hello_agents/__init__.py`

**改动**: 添加 `rag` 和 `mcp` 子包的延迟导入（lazy import），保持与现有导出风格的兼容。

```python
# 在 __init__.py 末尾追加 RAG 和 MCP 的延迟导入
# RAG (lazy)
def _get_rag_pipeline():
    from hello_agents.rag import create_rag_pipeline
    return create_rag_pipeline

# MCP (lazy) 
def _get_mcp_client():
    from hello_agents.mcp import MCPClient, MCPServer
    return MCPClient, MCPServer
```

**验收**:
- [ ] `import hello_agents` 不触发 RAG/MCP 的依赖加载
- [ ] 可选的 RAG/MCP 依赖缺失不影响框架其他部分的正常使用

---

### Task 6: 清理 + 验证

**操作**:
- [ ] 删除根目录 `rag/` 文件夹
- [ ] 删除根目录 `protocols/` 文件夹
- [ ] 运行 `python -c "from hello_agents.rag import create_rag_pipeline; print('RAG OK')"`
- [ ] 运行 `python -c "from hello_agents.mcp import MCPClient, MCPServer; print('MCP OK')"`
- [ ] 运行 `python -c "from hello_agents.embedding import LocalTransformerEmbedding; print('Embedding OK')"`
- [ ] 运行 `python -c "from hello_agents.storage import QdrantVectorStore; print('Storage OK')"`
- [ ] 运行现有测试套件 `python -m pytest tests/ -x --timeout=60` 确保无回归
- [ ] 撰写 `docs/rag-mcp-integration-report.md` 集成报告

---

## 执行顺序

```
Task 1 (embedding) ──┐
                      ├──→ Task 3 (rag 修复) ──→ Task 5 (更新 __init__) ──→ Task 6 (清理+验证)
Task 2 (storage)    ──┘
Task 4 (mcp)        ─────────────────────────────────────────────────────────┘ (独立)
```

- Task 1, 2, 4 可并行
- Task 3 依赖 Task 1 和 2
- Task 5 依赖 Task 3 和 4
- Task 6 最后执行

---

## 风险与缓解

| 风险 | 缓解方案 |
|------|---------|
| `fastmcp` 版本 API 不兼容 | `__init__.py` 已做 try/except 保护；未安装时提供清晰错误信息 |
| Qdrant 服务不可用 | QdrantVectorStore 支持 `QDRANT_URL` 环境变量；无服务时使用本地文件模式或 memory 模式 |
| `sentence-transformers` 下载模型慢 | factory 函数支持模型本地路径 + TFIDF fallback |
| 现有测试因新模块而失败 | 新模块使用延迟导入，不影响不相关的测试 |

---

## 验证方案

完成全部 6 个 Task 后，运行以下端到端验证：

```bash
# 1. 导入验证
python -c "
from hello_agents.embedding import create_embedding_model_with_fallback
from hello_agents.storage.qdrant_store import QdrantVectorStore
from hello_agents.rag import create_rag_pipeline
from hello_agents.mcp import MCPClient, MCPServer, create_context
print('All imports successful')
"

# 2. RAG Pipeline 集成测试 (需 Qdrant)
python -c "
from hello_agents.rag import create_rag_pipeline
pipe = create_rag_pipeline(rag_namespace='test')
print(f'Pipeline created: {list(pipe.keys())}')
# 添加一个测试文档
import tempfile, os
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
    f.write('# Test\n\nThis is a test document about machine learning.')
    tmp = f.name
pipe['add_documents']([tmp])
os.unlink(tmp)
# 搜索
results = pipe['search']('machine learning', top_k=3)
print(f'Search results: {len(results)} items')
"

# 3. 现有测试无回归
python -m pytest tests/ -x --timeout=60 -q
```

---

## Phase 3 补充 (2026-05-19)

Phase 1 建立的 embedding/storage 共享层在 Phase 3 中进一步承载了 Memory 子系统：

- `hello_agents/memory/` 从原框架删除的 hello_memory 代码中恢复并迁移（与 rag/ 迁移模式一致）
- Memory 类型（Episodic/Semantic/Perceptual）使用 `hello_agents.embedding` 和 `hello_agents.storage.qdrant_store`，无重复
- `QdrantConnectionManager` 添加了 `get_instance()` 兼容方法和连接超时
- 相关修复：Windows GBK emoji、reasoner 模型 tool_choice cascade、reasoning_content 回传（3 处）

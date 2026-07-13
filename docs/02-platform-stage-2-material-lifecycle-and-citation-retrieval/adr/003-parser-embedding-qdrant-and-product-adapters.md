# ADR 003：Parser、Embedding、Qdrant 与产品适配边界

状态：已接受
接受日期：2026-07-11
日期：2026-07-11
适用阶段：Platform Stage 2 Slice 1

## 1. 背景

仓库已有 `hello_agents` embedding、Qdrant store 和宽泛 RAG pipeline，也有 `academic_companion` ingestion demo。这些资产证明能力可行，但当前接口包含环境变量耦合、隐式 TF-IDF fallback、宽泛格式识别、prototype payload，以及维度不匹配时自动删除 collection 等产品不可接受行为。

Stage 2 需要复用能力，而不是让 prototype 合同定义产品状态。

## 2. 决策

在 `apps/api` 建立窄的产品 adapter protocol，并在 worker 中组合：

```text
StorageAdapter
ParserRegistry -> ParsedDocument
Chunker -> SourceChunk[]
EmbeddingAdapter -> vectors
SourceChunkIndex -> Qdrant
```

产品 service 只依赖这些 protocol。允许 adapter 内部调用稳定的 `hello_agents` 能力，但不得直接调用 `academic_companion` API/Web 或 `hello_agents.rag.pipeline` 的高层 ingestion 函数。

### 2.1 Parser

- TXT/Markdown 使用受控文本读取器；Markdown 提取标题路径。
- PDF 使用 `pypdf` 处理含文本层 PDF。
- parser 输出统一 `ParsedDocument`：规范化文本、页/段落定位、heading markers、warning codes 和 parser version。
- PDF 文本为空或低于可用阈值时返回 `ocr_required`，不静默 OCR。
- 加密、损坏或超限文件使用稳定错误码。

不使用 MarkItDown 作为 Slice 1 总入口。原因是其支持面远超已确认格式，可能隐式引入 Office、OCR、音频、网页和压缩包行为。

### 2.2 Chunking

采用确定性、heading-aware 的字符切块：默认目标 800 字符、重叠 100 字符，优先在标题、空行和句末断开。配置写入 version/job 处理摘要；相同规范化文本与配置必须产生相同 ordinal、offset、hash 和 chunk ID。

字符切块不是永久算法。选择它是为了 Slice 1 可复验，避免不同 tokenizer/provider 改变引用 offset。后续替换算法必须创建新的 processing generation 或 version，不原地改变 ready chunk。

### 2.3 Embedding

- Slice 1 默认使用已配置的 DashScope。产品 adapter 优先调用支持 `text_type` 的 DashScope 原生同步 HTTP API；不把 OpenAI-compatible 形式当作必须合同。
- 建议默认模型 `text-embedding-v4`、1024 维、dense float、cosine；若现有账户只验证过 `text-embedding-v3`，可在 provider smoke 后显式改为 v3，但 model 与 dimension 必须成对固定。
- 索引文档时使用 `text_type=document`，查询时使用 `text_type=query`；adapter 按 provider 限制分批，当前每批最多 10 条。
- 产品配置使用 `PRODUCT_EMBEDDING_PROVIDER`、`PRODUCT_EMBEDDING_MODEL`、`PRODUCT_EMBEDDING_DIMENSION`、`PRODUCT_EMBEDDING_BASE_URL` 和 `PRODUCT_EMBEDDING_API_KEY`，不让 runtime 隐式读取 prototype 的 `EMBED_*`。现有 DashScope key 可以迁入新的产品变量，不提交 Git。
- model、dimension、text type 和 output type 是索引合同，启动及 collection 初始化时校验。
- 禁止隐式切换到本地模型、TF-IDF 或不同维度；provider 不可用时 ingestion job 明确失败，查询返回可诊断的 503。
- 测试使用固定 deterministic fake embedding，不调用真实 provider；真实 DashScope 调用只在显式 provider smoke 中执行。

本地 sentence-transformers 保留为可选 adapter，而不是自动 fallback。选择本地模式需要显式配置模型、维度和镜像构建方式，并重建独立 collection。

### 2.4 Qdrant

产品使用 `qdrant-client` 建立自己的 `SourceChunkIndex`，不直接复用会自动删除 collection 的现有 store 行为。

- 默认 collection：`learn_platform_source_chunks_v1`。
- schema version 写入 payload。
- collection 不存在时允许创建；配置不兼容时明确失败。
- 查询构造强制 workspace match filter，不能由调用方省略。
- payload 不保存唯一正文。
- delete/rebuild 使用 document/version/chunk ID filter 或稳定 point ID。

### 2.5 依赖与镜像

- parser、RQ、Qdrant client 和 embedding adapter 依赖属于 `apps/api` 产品依赖。
- worker 与 API 共享 product package 和基础镜像，避免两套合同；可在后续优化为独立镜像 target。
- 若复用 `hello_agents.embedding`，Docker build 必须以显式安装本地 package 的方式引入，不能依赖源码偶然出现在 `PYTHONPATH`。
- `academic_companion` 仅提供 fixture、失败经验和候选算法，不进入 Slice 1 runtime import graph。

## 3. 影响

### 正向

- 产品 API 与 prototype RAG 解耦。
- parser 支持面与用户承诺一致。
- embedding 维度不会静默漂移或破坏 collection。
- adapter 可用 fake 实现做快速离线测试。

### 成本

- 需要写少量产品 adapter，不能直接调用现有“一键 ingestion”。
- DashScope 会产生按量调用成本，并要求 worker/API 能访问外网。
- 资料 chunk 会发送给外部 embedding provider；部署者必须接受这一隐私边界。
- provider 限流或区域故障会使 ingestion 延迟或查询暂时不可用，需要退避和可重试错误。

## 4. 未采用方案

### 直接复用 `hello_agents.rag.pipeline`

不采用。它的 parser、fallback、环境变量、payload 和可选 LLM 扩展超出产品合同。

### 复制现有 RAG 代码到 `apps/api`

不采用。adapter 应复用稳定底层库或明确接口，不复制大段原型实现。

### 默认本地 sentence-transformers

暂不采用为默认。虽然完全离线，但会增加镜像体积、首次模型下载、CPU/内存需求和跨机器复现成本；当前项目已经配置 DashScope，更适合作为第一条稳定路径。

### 自动 fallback 到 TF-IDF

不采用。维度与语义改变会使索引不可比较，且用户无法从 job 状态判断真实模型。

## 5. 待人工选择

本 ADR 推荐 DashScope `text-embedding-v4`、1024 维作为 Slice 1 默认合同。人工 gate 需要确认：现有 key 对该模型可用、部署者接受资料片段发往 DashScope、预算可接受，并通过一组中文检索 smoke。若选择已使用的 `text-embedding-v3`，也必须固定为显式 model/dimension，不能只写“使用 DashScope 默认模型”。

## 6. 生效条件

与 Spec 001 一并确认后生效。实现前需要完成固定 fixture 的 parser/chunk 快照测试、fake embedding 索引测试，以及一次显式 DashScope document/query embedding + Qdrant smoke。

# ADR 005：带引用回答、生成 Provider 与 Agent 边界

状态：已接受
接受日期：2026-07-13
日期：2026-07-13
适用阶段：Platform Stage 2 Slice 2

## 1. 决策摘要

Slice 2 使用一个窄的 `CitedAnswerService` 完成单轮同步回答：权威检索、证据包构造、一次结构化 LLM 生成、一次可选格式修复和严格 citation 校验。它不是 Tutor Agent，不使用工具循环、规划、memory、会话或 `agent_run`。

## 2. 背景

路线图要求 Stage 2 提供带引用自然语言答案，Stage 3 才引入 Course Architect、Lesson Writer 和 Tutor。若 Slice 2 直接包装 `LearningAgent` 或 ReAct Agent，会同时引入对话状态、工具权限、循环终止、memory 和 trace 等尚未评审的合同。若只让模型输出自由文本加 `[1]`，又无法可靠验证引用是否存在或属于当前 workspace。

## 3. 决策

### 3.1 执行流程

1. 校验 workspace、问题长度、`top_k` 和可选 document filter；`top_k` 默认 5，范围 1..20。
2. 计算 `candidate_k=min(top_k*3, 50)`，调用 Qdrant 做 query embedding 相似度召回。
3. Qdrant 查询强制 workspace filter；可选 document filter 同样下推，但候选仍不视为权威结果。
4. 按候选 ID 批量回读 Postgres，过滤 workspace/document 不匹配、document 非 active、version 非 current/ready、重复或已删除 chunk。
5. 保持 Qdrant score 顺序，应用统一相关性门禁后再截取最多 `top_k` 个有效证据：短关键词必须有完整词面命中；其他查询必须有词面支持或达到保守语义阈值。
6. 为证据分配请求内 citation ID，并按 generation token 预算依次装入证据包；未装入的候选不能被引用。
7. 无有效证据时返回 `insufficient_evidence`，不调用模型。
8. 调用 generation adapter，要求返回结构化 claims。
9. 校验 JSON schema、claim 非空、citation ID 存在且至少一个。
10. 非法格式最多执行一次受限 repair；仍失败则返回 `invalid_model_output`。
11. API 以权威 chunk 回读组装 citation，不信任模型返回正文或资料元数据。

选择三倍候选数是为了抵消 Qdrant 陈旧 point 和权威回读过滤，但设置 50 的硬上限避免候选查询与数据库回读无界增长。该比例和最终 `top_k` 进入 trace 与 eval；Slice 2 不增加 reranker、相邻 chunk 合并、MQE 或 HyDE。

### 3.2 输出结构

模型只返回：

```json
{
  "claims": [
    {"text": "一条资料性陈述", "citation_ids": ["c1"]}
  ],
  "limitations": []
}
```

- citation ID 只能来自服务端证据包。
- claim 没有引用、引用未知 ID、claims 为空或输出不是有效 schema 时不得作为成功回答返回。
- 服务端不声称能自动证明“引用语义完全蕴含 claim”；Slice 2 通过受控证据、结构化输出、离线 eval 和人工样例降低风险。成功回答不展示模型自由生成的 limitations；资料不足由服务端在调用模型前返回。

### 3.3 无证据阈值

“证据不足”由检索结果数量、权威回读存活数量和显式相关性门禁共同决定。阈值写入产品配置和 trace，不由 prompt 临时决定。低于门禁的候选不返回给用户，也不得调用 LLM 生成肯定答案。

2026-07-13 的真实资料 smoke 显示，未设下限时，完全无关的短关键词仍会被 Qdrant Top-K 返回，且可继续触发回答。单一分数阈值又会误伤当前 embedding 下资料名或正文明确匹配、但分数较低的中文资料。因此采用保守混合门禁：

- 短关键词查询必须在 chunk 正文、标题路径或资料显示名中完整出现；
- 其他查询满足词面支持，或分数不低于 `PRODUCT_RAG_MIN_SCORE=0.50`；
- 相关性由共享 `retrieve` 服务一次判定，`/rag/query` 与 `/rag/answer` 不得各自再实现不同阈值。

这项策略优先减少无关引用和无依据回答；固定 RAG eval 以后可显式调整阈值，或以新 ADR 批准 reranker。

### 3.4 Provider 配置

Embedding provider 和 generation provider 是两个不同职责：

| Provider | 输入 | 输出 | 当前用途 |
|---|---|---|---|
| Embedding | 问题或资料片段 | 向量 | Qdrant 相似度召回，已确认使用 DashScope |
| Generation | 问题与最终证据包 | 自然语言 claims + citation IDs | Slice 2 新增的带引用回答 |

generation provider 就是外部大模型 API。它可以与 embedding 使用同一厂商，甚至部署者可以把同一实际 API key 分别填入两个配置项；但代码不能假设二者共享 key、base URL、模型、超时或隐私边界。

- 新增独立产品配置：`PRODUCT_GENERATION_PROVIDER`、`PRODUCT_GENERATION_MODEL`、`PRODUCT_GENERATION_BASE_URL`、`PRODUCT_GENERATION_API_KEY`、`PRODUCT_GENERATION_TIMEOUT_SECONDS`、`PRODUCT_GENERATION_THINKING`。
- 不隐式读取根 framework 的 `LLM_*`，也不复用 `PRODUCT_EMBEDDING_API_KEY`。
- 首个 adapter 采用 DeepSeek 官方 OpenAI-compatible Chat Completions：base URL `https://api.deepseek.com`，默认 model `deepseek-v4-flash`，`thinking=disabled`，`response_format={"type":"json_object"}`。未配置 key 时 `/rag/answer` 返回可诊断 503。
- 可在 adapter 内复用 `hello_agents` 的稳定低层 LLM client，但不得调用 Agent、memory、tool 或 prototype API。
- provider 失败时不切换模型、不切换供应商、不退化成无引用自由回答。

Flash 足以作为首个默认模型：本切片已经完成证据检索，不要求模型自主搜索、工具调用或复杂规划，主要任务是根据最多 5 条证据生成短 claims 并遵循 JSON/citation 结构。DeepSeek 官方当前为 Flash 和 Pro 都提供 JSON Output；Flash 的输入、输出价格约为 Pro 的三分之一，且并发上限更高。

模型名、能力与价格依据 [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)；非思考模式使用官方 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode) 的 `thinking.type=disabled`；结构化输出遵循 [JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/) 的 `response_format={"type":"json_object"}`。这些外部事实可能变化，开发与部署 smoke 时必须重新核对官方文档和 `/models`，不能只依赖本 ADR 的日期快照。

Pro 不作为按请求自动 fallback。只有当固定 eval 证明 Flash 在跨资料冲突、长证据或 citation 遵循率上未达到验收线时，才由部署者显式把 model 改为 `deepseek-v4-pro`，并复跑 provider smoke 与 eval。模型选择和 thinking 开关写入 answer trace。

选择非思考模式是因为当前任务短、结构明确，并且不需要把额外 reasoning token 计入延迟和成本。若后续证明复杂问题需要思考模式，同样通过显式配置和 eval 修改，不按问题自动切换。

### 3.5 Generation 输入与输出示例

服务端构造的概念证据包：

```text
QUESTION
资料如何定义任务重试的幂等性？

EVIDENCE
[c1] 任务设计.md / 幂等
重复执行同一业务 job 时，稳定 chunk ID 和 point ID 覆盖原结果，而不是追加副本。

[c2] 任务设计.md / 重试
job 已 queued 或 running 时，重复 retry 返回当前状态，不再次 enqueue。
```

模型只能返回：

```json
{
  "claims": [
    {
      "text": "任务重试通过稳定身份和覆盖式写入避免重复结果。",
      "citation_ids": ["c1"]
    },
    {
      "text": "运行中或已排队的任务不会因重复重试而再次入队。",
      "citation_ids": ["c2"]
    }
  ],
  "limitations": []
}
```

服务端拒绝未知 citation ID，忽略模型尝试返回的 document/chunk 元数据，并从 Postgres 权威记录生成最终 citations。

### 3.6 同步与持久化

- Slice 2 首版采用同步、非流式请求，设置明确 provider 和总请求超时。
- Postgres 保存 answer trace 元数据、证据/citation ID、token 用量、延迟、状态与 hash；默认不保存完整问题、完整 prompt、回答正文或 provider 原始响应。
- 因不保存回答正文，刷新页面后不提供回答历史。这是有意边界，Stage 3 Tutor/session 再决定会话持久化。

### 3.7 Agent 边界

本服务明确不具备：

- 多步规划或反思；
- 工具调用、网页搜索、MCP 或 research pipeline；
- 长期/短期 memory；
- 会话历史与自主继续运行；
- `LearningAgent`、ReAct、PlanSolve 或多 Agent orchestration。

Stage 3 可以把 `CitedAnswerService` 的检索、证据和 citation validation 作为 Tutor 的受控能力，但必须另写 Spec/ADR 决定 Agent runtime、工具权限、session、memory 和 run trace。

## 4. 安全与隐私

- prompt 把资料 chunk 视为不可信内容，明确禁止其中指令改变系统规则或请求外部工具。
- 不把 workspace 外资料、已删除资料、非 current version 或 Qdrant payload 正文放入 prompt。
- 日志只记录 trace ID、hash、数量、模型、延迟、安全错误和 token 用量。
- provider 原始错误经过映射；不得向用户或普通日志返回请求体、响应体、key 或内部 URL。
- 问题和证据包有长度预算，避免 prompt 成本无界增长。

## 5. 影响

### 正向

- 引用身份由服务端控制，模型不能伪造 document/chunk 元数据。
- Stage 2 能交付自然语言价值，又不提前固化 Tutor Agent。
- generation provider 与 embedding provider 可独立选择和计费。
- trace 能支持后续 citation eval 与成本分析。

### 成本

- 结构化输出兼容性需要 fake provider、真实 provider smoke 和修复路径测试。
- 同步非流式请求在慢 provider 下体验较弱。
- 不保存回答正文意味着没有历史记录或刷新恢复。
- 引用存在不等于语义完全正确，仍需 eval 和人工评审。

## 6. 未采用方案

### 直接使用 Tutor/LearningAgent

不采用。会提前引入 Stage 3 的 session、memory、工具和 Agent trace 合同。

### 自由文本中解析 `[1]`

不采用。自由格式容易出现漏引、越界引用和渲染歧义。

### 没有证据时让模型依靠常识回答

不采用。Stage 2 的产品承诺是资料驱动与可解释，不是通用问答。

### 失败时回退到另一个 provider 或无引用答案

不采用。模型、成本、隐私和行为会静默改变。

### Stage 2 建立聊天历史

不采用。回答历史涉及新的内容所有权、删除、保留与 session 模型，应由 Stage 3 决定。

## 7. 待人工确认

已确认：

1. generation provider 使用 DeepSeek 官方 API，默认 `deepseek-v4-flash` 非思考模式。
2. 同步非流式首版，不保存完整问题和回答历史。
3. 默认 `top_k=5`，候选扩展为 `candidate_k=15`；自定义 top-k 时仍按三倍召回并封顶 50。

实现前验证项：

4. Flash 的 JSON/claim/citation 遵循率必须通过 fake provider tests、固定 eval 和一次真实 smoke。
5. 最低相关度由固定 eval 确认后进入配置，不预设未经验证的魔法分数。
6. Flash 未达验收线时才人工切换 Pro；不实现自动模型 fallback。

## 8. 生效条件

与 Spec 002 一并接受，并完成 fake provider 的结构化输出/失败测试以及一次显式真实 provider smoke 后生效。

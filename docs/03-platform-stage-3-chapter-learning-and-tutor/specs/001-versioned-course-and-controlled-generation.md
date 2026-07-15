# Spec 001：版本化课程与受控课程生成

状态：已接受（2026-07-14 人工 Gate）

日期：2026-07-13

适用阶段：Platform Stage 3 Slice 1

## 1. 评审结论摘要

本规格定义 Stage 3 的第一条纵向用户路径：用户从 workspace 中选择已经 ready 的资料，创建一个课程生成任务，审阅 Course Architect 生成的章节大纲，按需让 Lesson Writer 生成单个课节，发布课节版本，再激活课程版本并进入 Course Reader 阅读。

Slice 1 会首次引入真正受控的产品 Agent，但不会直接复用现有 `LearningAgent`，也不会提前实现 Tutor 对话、长期 Memory、Skill、MCP 或自由多 Agent 协作。Agent 只能通过产品提供的证据检索和结构化提交工具工作；Postgres 继续拥有课程、版本、任务、引用和运行轨迹事实。

评审时应重点确认八件事：Slice 1 是否应覆盖“大纲 -> 单课节 -> Reader”的完整纵向路径；课程与课节的版本/发布语义；资料版本快照与删除后的行为；Agent 是否采用受控双角色；生成成本是否按课节显式触发；最小 run/tool trace 是否足够；外部 provider 数据披露是否明确；以及哪些能力必须留到后续切片。

## 2. 背景与当前事实

Stage 2 已提供：

- workspace、document、document version、chunk、ingestion job 与 citation 的 Postgres 合同；
- PDF/Markdown/TXT 入库、DashScope embedding、Qdrant 检索和 Postgres 权威回读；
- 默认 `top_k=5`、三倍候选召回、相关性门禁和资料不足拒答；
- DeepSeek Flash 的受引用单轮回答与 answer trace；
- Redis/RQ worker、lease/heartbeat、重试、取消、reconciler 和资源预算模式。

当前 `academic_companion.agents.LearningAgent` 是重要参考资产，但不能直接成为产品 Agent：它绑定内置 CS/LeetCode RAG、本地 UserModel/Memory、TodoWrite、原型章节字典和无产品所有权的 session；若直接接入会绕过 workspace、资料版本、删除、引用与 Postgres 事实合同。

研究 pipeline 的结构化上下文交接、`hello_agents` 的 ReAct/Tool/Skill/trace 能力可以作为实现证据，但采用方式必须由本 Stage ADR 控制。

## 3. 目标

建立可审阅、可版本化、可追溯、可按成本渐进生成的课程基础，使用户能够：

1. 从当前 workspace 选择 1 至 20 份 ready 资料并声明课程目标；
2. 显式确认所选资料片段会发送给已配置 generation provider；
3. 异步获得一个带来源支撑的课程大纲草稿；
4. 为大纲中的单个课节按需生成内容，而不是自动批量消耗所有课节成本；
5. 审阅并发布课节版本，再激活课程版本；
6. 在 Course Reader 中阅读已发布内容并定位资料引用；
7. 在失败、取消、资料变化或 provider 不可用时看到明确状态并安全重试。

## 4. 成功标准

Slice 1 完成时必须同时满足：

- 课程、课程版本、章节、课节、课节版本、来源快照和引用均可追溯到 workspace。
- 创建课程不会在 HTTP 请求内执行 Agent；API 先持久化 course/job，再进入 Redis 队列。
- Course Architect 只能检索所选资料的精确版本，并提交符合 schema 的大纲 artifact。
- Lesson Writer 只能围绕目标课节和同一课程来源快照检索，并提交逐块带 citation 的课节 artifact。
- 失败的大纲重生成不覆盖当前激活课程；失败的课节重生成不覆盖已发布课节。
- 用户可以一次只生成一个课节，并在外部调用前看到 provider 与数据外发提示。
- Course Reader 只把激活课程版本中的已发布课节当作正式内容；未生成课节明确显示状态。
- 第一个 Agent 同时产生最小 `agent_run` 和 `agent_tool_call` 轨迹，不记录原始 prompt、资料正文、key 或内部 URL。
- API focused tests、migration test、fake provider/agent tests、Web lint/build、Compose smoke、固定 eval 与人工浏览器 smoke 均有记录。

## 5. 约束与不变量

- 依赖方向保持 `apps -> academic_companion -> hello_agents`；领域 Agent 不 import 产品 ORM、router 或 settings。
- Postgres 是课程、任务、发布状态、引用和 Agent 运行事实来源；Qdrant 仍只是资料检索索引；Redis 不拥有唯一任务状态。
- 课程生成必须使用 Stage 2 资料和 citation 合同，不直接调用原型 `RAGRetrievalTool` 或 `hello_agents.rag.pipeline`。
- 所有生成均由用户显式触发；不在上传、激活、页面打开或定时任务中自动发送资料到外部 provider。
- provider 失败不切换模型、不切换供应商、不降级为无引用自由生成。
- 资料 chunk 属于不可信输入，不能通过 prompt injection 获得新工具、修改系统规则或扩大 workspace/source scope。
- 当前仍是单用户 self-host，但所有课程数据保留 workspace 外键与过滤纪律。

## 6. 范围

### 6.1 范围内

- 课程稳定身份、版本化大纲、章节与课节占位。
- Course Architect 和 Lesson Writer 两个受控角色。
- 课程来源的 document/version 快照。
- 大纲异步生成、单课节异步生成、失败/重试/取消。
- 大纲草稿激活、课节草稿发布和历史版本保留。
- 章节/课节 citation 与资料定位。
- 最小 Agent run/tool trace。
- Workspace 内的课程列表、创建/生成状态、大纲审阅和 Course Reader。
- 最小 outline/lesson/citation eval。

### 6.2 明确不做

- Tutor 多轮对话、SSE、聊天历史和会话恢复。
- Working/Episodic/Semantic 长期 Memory、掌握度、复习队列。
- Skill 自动选择、MCP、网页搜索或外部学术资料补充。
- Agent 自主委派、开放式多 Agent 群聊或通用编排平台。
- 练习题、评分、rubric、attempt 和学习进度更新。
- 自动批量生成整门课程、自动发布或无人确认的后台重生成。
- 手工富文本编辑器、协同编辑、公开分享和多用户权限。
- OCR/Office/网页/Git parser extension。

这些能力并未被永久排除；它们应在本 Slice 的课程事实、引用和 Agent 运行合同稳定后，按后续 Spec/ADR 单独分析。

## 7. 核心概念

| 概念 | 含义 |
|---|---|
| Course | workspace 内的稳定课程身份，保存标题、目标、受众与生命周期 |
| Course Version | 一次不可变的大纲版本，包含精确来源快照、章节与课节占位 |
| Section | Course Version 内有序章节，包含标题和学习目标 |
| Lesson | Section 内有序课节身份；课节内容通过 Lesson Version 演进 |
| Lesson Version | 一次不可变课节草稿或已发布内容，保存结构化内容和引用 |
| Source Snapshot | 生成时固定的 active/current/ready document version 集合 |
| Generation Job | Postgres 权威异步任务，类型为 `course_outline` 或 `lesson_draft` |
| Agent Run | 某个 job attempt 中 Course Architect 或 Lesson Writer 的可审计运行 |
| Tool Call | Agent 对产品证据工具或 artifact 提交工具的一次调用记录 |

## 8. 用户流程

### 8.1 创建课程并生成大纲

1. 用户进入 workspace 的“课程”入口。
2. Web 只列出 active、current、ready 的资料版本供选择。
3. 用户填写课程标题、学习目标和可选受众，选择 1 至 20 份资料。
4. Web 明确显示：“生成会把检索到的所选资料片段发送给 DeepSeek（或当前配置 provider）”。
5. 用户点击“创建并生成大纲”；请求携带 `Idempotency-Key` 和 `external_processing_ack=true`。
6. API 在同一事务中创建 Course 与 `course_outline` job，固定来源版本并返回 202。
7. Course Architect 最多生成 15 个 Section；每个 Section 包含 1 至 3 个 Lesson 占位和来源 citation。
8. schema/citation 校验通过后，服务原子创建新的 Course Version；失败不产生半成品版本。

### 8.2 审阅大纲与生成课节

1. 用户打开大纲草稿，查看章节、目标、课节占位和来源覆盖。
2. 用户可放弃草稿或再次生成新大纲；Slice 1 不提供任意正文编辑。
3. 用户对一个 Lesson 点击“生成课节”。每次只创建一个 `lesson_draft` job。
4. Lesson Writer 根据该 Lesson 目标和 Course Version 的来源快照检索证据。
5. 有效输出创建新的 Lesson Version 草稿；失败或取消不改变已发布版本。
6. 用户审阅课节内容和引用后显式发布该 Lesson Version。

### 8.3 激活课程与阅读

1. Course Version 至少有一个已发布 Lesson Version 后才允许激活。
2. 激活新 Course Version 原子替换 `current_active_version_id`；旧版本进入 archived，但仍可通过历史 API 查看。
3. Course Reader 展示当前激活大纲，已发布课节可阅读；未生成或仅有草稿的课节显示明确状态。
4. citation 的用户可读展示按“文件名 > 章节路径 > 第 N-M 页”逐级提供已有信息；内部 document/version/chunk ID 和字符偏移保留用于服务端校验，不作为主展示。非 PDF 或旧资料没有页码时允许省略页码；资料不可用时显示原因，不伪造可点击来源。
5. 后续仍可为激活版本的其他 Lesson 生成并发布内容，但不能原地修改已有 Lesson Version。

### 8.4 来源变化

- 大纲和课节生成只接受 job 创建时仍为 active/current/ready 的精确 document version。
- 在执行前或执行中发现来源删除、换版或不再 ready，job 以 `source_snapshot_stale` 失败，不静默改用新版本。
- 已激活课程是独立用户资源；删除来源不会静默删除课程，但课程进入 `source_degraded` 可见状态，受影响 citation 标记不可用，并阻止新的生成、发布或激活。
- 删除资料前 Web 应显示受影响课程数量；用户可保留降级课程、删除课程，或基于新的来源生成新 Course Version。

## 9. API 合同

所有路径均位于 `/api/v1/workspaces/{workspace_id}`，并强制 workspace 权威过滤。

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/courses` | 列出课程、当前激活版本和最新 job 摘要 |
| `POST` | `/courses` | 创建 Course、来源快照和首个大纲 job；需要 `Idempotency-Key`，返回 202 |
| `GET` | `/courses/{course_id}` | 返回课程、版本摘要、章节/课节状态和来源状态 |
| `POST` | `/courses/{course_id}/outline-generations` | 以明确来源版本创建新大纲 job；请求必须携带 `external_processing_ack=true`，返回 202 |
| `GET` | `/course-generation-jobs/{job_id}` | 查询大纲或课节任务状态 |
| `POST` | `/course-generation-jobs/{job_id}/retry` | 对 retryable job 增加 attempt，不创建重复 Course/Lesson Version |
| `POST` | `/course-generation-jobs/{job_id}/cancel` | 请求取消；已提交成功 artifact 不回滚 |
| `POST` | `/courses/{course_id}/versions/{version_id}/activate` | 激活合格 Course Version |
| `POST` | `/courses/{course_id}/versions/{version_id}/lessons/{lesson_id}/generations` | 创建单课节生成 job；请求必须携带 `external_processing_ack=true`，返回 202 |
| `POST` | `/lessons/{lesson_id}/versions/{lesson_version_id}/publish` | 发布有效 Lesson Version |
| `GET` | `/courses/{course_id}/reader` | 返回当前激活大纲、课节发布状态和引用数据 |
| `DELETE` | `/courses/{course_id}` | Course 立即对默认列表/Reader 不可见；不删除来源资料 |

### 9.1 创建课程请求示例

```json
{
  "title": "搜索与推荐系统入门",
  "goal": "理解召回、排序和离线评估的基本链路",
  "audience": "具备基础 Python 的学习者",
  "document_ids": ["doc-1", "doc-2"],
  "external_processing_ack": true
}
```

返回 202，响应包含 course、固定的 document version IDs 和 generation job；不在响应等待 Agent 完成。

## 10. 结构化 Agent Artifact

### 10.1 Course Architect 输出

```json
{
  "title": "搜索与推荐系统入门",
  "summary": "从候选召回到排序评估的渐进课程。",
  "sections": [
    {
      "title": "召回阶段",
      "objective": "理解召回目标与常见策略。",
      "citation_ids": ["e1", "e2"],
      "lessons": [
        {
          "title": "为什么需要召回",
          "objective": "说明全量排序不可行的原因。",
          "citation_ids": ["e1"]
        }
      ]
    }
  ]
}
```

服务端验证 Section 为 1 至 15 个、每节 Lesson 为 1 至 3 个、标题/目标长度、所有 citation ID 的存在与 source scope。模型不能返回 document/version/chunk 元数据；服务端从证据表回填。

### 10.2 Lesson Writer 输出

```json
{
  "title": "为什么需要召回",
  "learning_objectives": ["解释候选集缩减的必要性"],
  "blocks": [
    {
      "block_key": "concept-1",
      "type": "paragraph",
      "text": "召回阶段先从大规模候选中筛出较小集合，供后续精排处理。",
      "citation_ids": ["e1"]
    },
    {
      "block_key": "summary-1",
      "type": "summary",
      "text": "召回关注覆盖和效率，排序关注候选间的精细比较。",
      "citation_ids": ["e1", "e2"]
    }
  ]
}
```

Slice 1 仅允许 `heading`、`paragraph`、`example`、`summary` 四类 block。除纯标题外，每个事实 block 至少有一个有效 citation；未知 citation、空正文、重复 `block_key` 或超预算输出整体失败，不静默删除坏块后标记成功。

## 11. Agent 与工具边界

### Course Architect

- 可调用 `CourseEvidenceSearch`：只检索当前 job 的 workspace 和 source snapshot；最多 5 次，每次 `top_k<=5`。
- 可调用 `SubmitCourseOutline`：只能提交一次结构化 artifact。
- 不可访问文件系统、MCP、网络搜索、Memory、TodoWrite、数据库或其他 Agent。

### Lesson Writer

- 可调用 `CourseEvidenceSearch`：额外受当前 Lesson objective 限制；最多 3 次。
- 可调用 `SubmitLessonDraft`：只能提交一次结构化 artifact。
- 不可改变课程大纲、来源集合、发布状态或调用 Course Architect。

每个 role 每次 attempt 使用全新 runtime，不共享隐式聊天历史。两个角色通过 Postgres 中的 Course Version/Lesson artifact 交接，而不是相互自由对话。产品 orchestrator 拥有 job、重试、取消、lease、预算和最终提交。

## 12. 状态与失败合同

### 12.1 Generation Job 状态

```text
queued -> running -> succeeded
                  -> retry_wait -> running
                  -> failed
                  -> canceled
queued/running/retry_wait -> cancel_requested -> canceled
```

### 12.2 主要错误码

| 错误码 | 用户语义 | 可重试 |
|---|---|---|
| `source_not_ready` | 创建时选择了非 ready 资料 | 否，重新选择 |
| `source_snapshot_stale` | 执行时来源已删除、换版或不再 ready | 否，生成新版本 |
| `external_processing_ack_required` | 未明确确认外部处理 | 否，确认后新建请求 |
| `generation_provider_unconfigured` | 未配置 generation provider | 配置后可重试 |
| `generation_provider_unavailable` | provider 超时或暂不可用 | 是，受 attempt 上限约束 |
| `agent_step_budget_exceeded` | Agent 超过步骤/工具预算 | 默认否，需检查 prompt/eval |
| `insufficient_evidence` | 合格证据不足以生成大纲或课节 | 否，补充资料或调整目标 |
| `invalid_agent_artifact` | 输出 schema/citation 无效，修复尝试后仍失败 | 是一次，之后人工处理 |
| `generation_canceled` | 用户取消或 worker 丢失所有权 | 是，可显式重建 job |
| `queue_failed` | Postgres 已保存但 Redis 投递失败 | 是，reconciler/显式 retry |

无论何种失败，都不得把部分 Course Version/Lesson Version 标记为 draft/published；已激活课程和已发布课节不受覆盖。

## 13. 资源、成本与安全

- 每个 Course 最多选择 20 份资料；Course Architect 最多 6 个 Agent step、5 次检索、15 个 Section、每节 3 个 Lesson。
- 每个 Lesson Writer 最多 4 个 Agent step、3 次检索；默认总证据预算 12,000 预估 token，输出预算由独立 Stage 3 配置限制。
- 大纲和课节使用显式异步任务；lesson 默认逐个生成，不提供“自动生成全部”按钮。
- Web 在每次新 job 前展示 provider、来源数量和外部处理提示；API 要求显式 ack，不能只依赖前端文案。
- 日志和 trace 只记录 ID、hash、角色、工具名、过滤摘要、数量、状态、延迟、token 和错误码。
- 不记录完整课程目标、原始检索 query、资料正文、完整 prompt、provider 原始响应或 API key。
- provider 输入把资料标记为不可信 evidence；Agent 工具参数由服务端覆盖 workspace/source filter，不能接受模型自行提供的 workspace ID。

## 14. Web 体验

- Workspace 增加“资料 / 课程”稳定入口；不把课程生成塞进现有资料卡内部。
- 课程列表展示标题、来源数、当前版本、已发布/待生成课节数、最新 job 与降级状态。
- 课程详情采用可扫描的大纲列表；每个 Lesson 有生成、失败、草稿、已发布状态和对应动作。
- Course Reader 使用稳定 URL，例如 `/workspaces/{workspace_id}/courses/{course_id}/reader`；刷新后从 API 恢复，不依赖 React 内存。
- Reader 主区显示课节正文，侧栏显示课程目录和 citation 来源；不是聊天首屏，也不在 Slice 1 放置 Tutor 输入框。
- 异步 job 轮询错误、取消、重试、provider 未配置和来源过期均必须显示，不以无限 spinner 代替失败。

## 15. 验证与 Eval

| 类别 | 最低覆盖 |
|---|---|
| Migration | 干净数据库升级；从 `0009` 升级；唯一约束、外键和状态索引 |
| API | workspace 隔离、幂等创建、来源快照、激活/发布冲突、删除和错误映射 |
| Worker | claim/lease、取消、重试、丢失所有权、原子 artifact 提交和 queue recovery |
| Fake Agent | 工具白名单、step/tool 预算、未知 citation、坏 schema、修复失败和 prompt injection fixture |
| RAG | 精确 source snapshot filter、资料不足、来源换版/删除、Postgres 权威回读 |
| Web | 创建、轮询、逐课节生成、发布、激活、刷新恢复、旧 workspace 响应隔离 |
| Eval | 固定小 corpus：outline coverage、citation validity、lesson factual support、拒绝无证据、token/latency |
| 实际栈 | Compose、`/ready`、Web HTTP 200、一个 synthetic course E2E |
| 人工 smoke | 一组无敏感资料完成大纲、一个课节、发布、激活和 Reader citation 定位 |

真实 provider smoke 必须使用可公开描述、无 key/隐私的 fixture，并在运行前明确告知调用范围和成本。较大代码、schema、Agent runtime 和删除行为进入 OCR gate；仍按风险块拆分，单块预计不超过 10 分钟且不设置 token 上限。

## 16. 建议实现顺序

1. migration 与 ORM：Course/Version/Section/Lesson/Source/Citation/GenerationJob/JobSource/AgentRun/ToolCall。
2. course service 与同步 API：创建、列表、详情、版本、激活/发布和 workspace 隔离。
3. generation queue、worker、lease/retry/cancel 与 fake orchestrator。
4. product-owned `CourseEvidenceSearch` 与 artifact validation。
5. `academic_companion` 中新的受控 Course Architect/Lesson Writer adapter，接入 `hello_agents` runtime。
6. Web 课程列表、大纲状态、逐课节生成和 Course Reader。
7. focused tests、migration、fake provider eval、Compose synthetic E2E。
8. 人工确认后执行真实 provider smoke 和 OCR，修复并归档阶段结果。

## 17. 人工 Gate

接受本 Spec 前需逐项确认：

1. Slice 1 交付“大纲草稿 -> 单课节生成/发布 -> 激活 -> Reader”的纵向路径，而不是只建 schema。
2. 每门课程最多 20 份来源；大纲最多 15 节，每节 1 至 3 个课节；课节默认逐个生成。
3. Course Version 固定精确 document versions；来源换版/删除后不静默切换，新的生成/发布/激活被阻止。
4. 来源删除不自动删除独立课程；课程保留但标记 `source_degraded`，受影响 citation 不可用，删除前展示影响。
5. 大纲与课节分别由 Course Architect/Lesson Writer 受控角色生成，通过 Postgres artifact 交接，不进行自由 Agent 对话。
6. Course Architect 最多 6 个决策 step、5 次证据检索；Lesson Writer 最多 4 个决策 step、3 次证据检索。检索和结构化提交都消耗 step，只允许产品证据工具和结构化提交工具。
7. Slice 1 不接入 Tutor、长期 Memory、Skill、MCP、练习或自动全课程生成。
8. 使用现有 `PRODUCT_GENERATION_*` provider/key 基础配置，并增加 Stage 3 角色预算；不自动 fallback。
9. 每次真实生成都需要用户显式外部处理确认；无确认不得调用 provider。
10. 最小 Agent run/tool trace 与首个 Agent 同时落地，完整 dashboard 留到 Stage 5。

本 Spec 及配套 ADR 已于 2026-07-14 通过人工 Gate；后续实现必须保持上述合同，发生实质偏离时先回到文档评审。

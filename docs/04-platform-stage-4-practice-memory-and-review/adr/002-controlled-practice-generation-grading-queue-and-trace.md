# ADR 002：受控练习生成、评分、队列与 trace

状态：已于 2026-07-16 通过人工 Gate

日期：2026-07-16

## 1. 决策摘要

Practice Set 生成由一个受控 Exercise Author 执行：它只能通过 `PracticeEvidenceSearch` 检索当前 Job 的精确来源快照，并通过结构化提交工具交付完整 artifact。它不是自由搜索或自主多 Agent。

单选题由产品服务确定性评分。简答题由独立、无检索工具的 Answer Grader 按该题固定 rubric/evidence 评估；它最多进行一次结构修复，不产生 fallback 分数。

生成与简答评分使用独立 `practice` RQ queue、Postgres Practice Job 权威状态、现有 lease/retry/cancel/reconciler 模式，并扩展 AgentRun/AgentToolCall 关联。Redis 丢失不丢失 Job 事实。

## 2. 背景

练习生成需要从课程来源中寻找可出题证据；简答评分还会处理用户答案。若直接调用 prototype Assessor，会绕过 source snapshot、citation、任务状态、取消、预算和安全 trace，并在失败时产生固定分数。

Stage 3 已有受控 Agent 和任务模式，可以复用工程结构，但不能简单把 CourseGenerationJob 塞入新的 job type：Practice 拥有不同 artifact、敏感答案、删除和评分重试语义。

## 3. 角色与工具

### 3.1 Exercise Author

- 输入：Lesson title/objective、允许公开的 Lesson learning objectives、输出语言、难度、题数和当前 Course Version source snapshot。
- 工具白名单：
  - `PracticeEvidenceSearch(query)`：服务端覆盖 workspace/course/version/source filter；最多 3 次，每次 `top_k <= 5`。
  - `SubmitPracticeSet(artifact)`：只接受结构化题目、answer spec、rubric 和临时 citation key。
- 最大 6 step；达到预算、取消、证据不足或未提交合法 artifact 时失败。
- 对来源文本使用“不可信 evidence”边界；任何 prompt injection 都不能增加工具、改变题数上限或扩大 scope。
- 完整 artifact 由服务端验证后一次性写入 Set/Items/Citations；不保存半成品。

### 3.2 Answer Grader

- 输入：单个不可变 Practice Item 的 rubric、answer spec、必要 evidence 和当前 Attempt answer。
- 没有 search、web、MCP、memory 或任意 tool 权限；评分阶段不扩大证据范围。
- 最多 2 次 provider call：初次结构化评估和一次 schema/citation 修复。
- 输出 verdict、可选 0-100 分、rubric 分项和反馈块；引用只能使用 Item ledger 中已有 key。
- 答案无法依据 rubric/资料判断时输出 `ungradable`；provider/结构失败则 Job 失败，不提交 Feedback。
- 用户答案始终作为不可信数据，不能修改评分规则、读取 system prompt 或请求其他工具。

### 3.3 单选评分服务

- 不调用 LLM，不创建 Answer Grader run。
- 在服务端比较 option key，事务内写 Attempt 和 Feedback。
- 正确答案解释和每个错误选项的 rationale/citation 都来自生成时已验证的 Practice Item，不在提交时重新生成。

## 4. Queue 与 Job

### 4.1 独立队列

- 增加 `practice` queue 和 practice worker；生成与简答评分共享该队列，但通过 Job type 分发。
- 不复用 ingestion/course/tutor queue，以避免长练习生成阻塞 Tutor 或把不同 lease/预算混在一起。
- API 先提交 Practice Job，再 enqueue；enqueue 失败标记 `queue_failed`，允许重试同一 Job。

### 4.2 Job 所有权

- `practice_jobs.job_type` 仅允许 `generate_set|grade_attempt`。
- Generation Job 固定 Course/Lesson Version、请求参数和 source rows；Grading Job 固定 Attempt。
- Idempotency-Key + canonical request hash 区分重复请求和冲突。
- worker 领取 row lock 后更新 `running`、worker id、lease、heartbeat 和 attempt count。
- transient provider/queue failure 进入有限 `retry_wait`；validation、scope、source stale 和预算失败不可自动换输入重试。
- reconciler 只恢复 stale/到期 Job，不重新创建业务资源。

### 4.3 取消与晚到结果

- queued/retry_wait 可以直接取消；running 进入 `cancel_requested`。
- worker 在检索前、provider call 前后和最终事务前检查取消及 Workspace/Course/Set/Attempt 状态。
- provider 已经返回但权威资源被删除或取消时，丢弃结果并记录稳定 canceled 状态。
- 取消 generation 不创建 Set；取消 grading 保留用户 Attempt，但不创建 Feedback，允许用户删除或显式重试。

## 5. 预算

候选默认值：

| 路径 | 预算 |
|---|---|
| Exercise Author | 6 step、3 search、6 provider call、24K evidence token、12K 总输出、10 分钟 wall time |
| Answer Grader | 0 search、2 provider call、12K evidence/rubric token、8,000 字符答案、3K 输出、3 分钟 wall time |

- 预算在服务端配置并由运行时强制，模型不能提高。
- token usage 缺失时记录“未报告”，不估算金额。
- 超限返回 `generation_budget_exceeded` 或 `grading_budget_exceeded`，不截断后提交。
- 真实 provider 观察必须另行确认 fixture、case 数和调用上限。

## 6. External processing 与隐私

- Generation Job 创建必须携带显式 acknowledgement，说明检索到的课程资料片段会发送给配置 provider。
- 每个简答 Attempt 提交必须携带 acknowledgement，说明该答案、rubric 和必要证据会发送给配置 provider。
- acknowledgement 时间写入业务记录；普通读取 API 不公开 provider key/base URL。
- Practice Job 和 AgentRun 不保存完整 prompt、用户答案、answer spec、rubric、evidence 正文、原始 response 或 provider error 正文。
- 日志只记录稳定业务 ID、状态和错误码；不记录题干、答案、feedback 或绝对路径。
- 脱敏运行摘要只增加任务身份、角色、状态、step/tool count、token、耗时和稳定错误码。

## 7. Trace

- 扩展 AgentRun 以关联 Practice Job；建议角色为 `exercise_author` 和 `answer_grader`。
- Exercise Author tool trace 只记录 `PracticeEvidenceSearch` / `SubmitPracticeSet` 名称、ordinal、状态、result count、latency 和稳定错误码。
- Answer Grader 可记录无 tool 的 AgentRun；若使用结构化提交工具，只记录 `SubmitPracticeFeedback` 的安全元数据。
- 单选确定性评分不伪装成 AgentRun；Attempt/Feedback 本身就是权威审计链。
- 删除 Attempt/Set/Course/Workspace 时按 ADR 001 删除对应 Practice Job 与 trace。

## 8. 错误码

至少定义：

- `source_snapshot_stale`
- `insufficient_evidence`
- `invalid_practice_artifact`
- `invalid_rubric`
- `unknown_citation`
- `answer_too_large`
- `grading_unavailable`
- `generation_budget_exceeded`
- `grading_budget_exceeded`
- `provider_unconfigured`
- `provider_unavailable`
- `queue_unavailable`
- `practice_canceled`
- `idempotency_key_conflict`

公开错误为稳定、简短中文说明；provider 原始错误只在受保护的本地诊断边界处理，不进入 API、日志或 OCR 副本。

## 9. 不采用的方案

### 方案 A：所有评分都交给 LLM

拒绝。单选有确定答案，使用 LLM 会增加成本和非确定性。

### 方案 B：评分时再次 RAG 检索

拒绝。会让同一题目的评分依据随索引和查询漂移；评分必须使用题目生成时固定的 rubric/evidence。

### 方案 C：失败时使用 fallback 题或固定 50 分

拒绝。会把 provider/结构失败伪装成用户学习结果，直接污染 Slice 2 的掌握度输入。

### 方案 D：复用 CourseGenerationJob 和 course queue

拒绝。Practice 有用户答案、评分重试、Attempt 删除和不同预算；混用会模糊所有权并增加队列干扰。

### 方案 E：同步完成生成和所有评分

拒绝。生成和简答评分依赖 provider，必须具有可见状态、取消、重试和晚到结果保护。

### 方案 F：把 Exercise Author 与 Answer Grader 做成可自由对话的多 Agent

拒绝。两者只通过结构化 Postgres artifact 交接；Grader 不需要自主工具循环。

## 10. 影响

### 正向

- 生成与评分各自有明确职责、预算和失败边界；
- 单选保持确定性，简答评估可追溯到固定 rubric/evidence；
- 用户答案不会进入通用 trace 或日志；
- queue/worker/reconciler 能沿用 Stage 3 已验证模式而不污染现有队列。

### 代价

- 增加独立 queue、worker、配置、Job owner 和 AgentRun 关联；
- 简答每次重做都可能产生 provider 成本和外部处理确认；
- 真实教学质量仍需人工 rubric 与多轮基线，不能只靠 schema tests。

## 11. 验证要求

- fake provider 固定矩阵覆盖单选、简答、中文、英文、无证据、未知 citation、invalid rubric、预算和取消；
- queue_failed/retry_wait/stale lease/reconciler/重复投递和晚到结果；
- prompt injection 不能扩大 workspace/source、题数、工具或预算；
- 简答答案不出现在日志、AgentRun、tool trace、运行摘要和 eval report；
- 单选不调用 provider；简答评分不调用 retrieval；
- OCR 按 migration/ORM、API/service、worker/runtime、Web/tests 风险块和隐私白名单执行。

## 12. 人工 Gate（已接受）

1. 是否接受 Exercise Author 是受控单 Agent，而 Answer Grader 是无检索工具的受控评估器，不引入多 Agent？
2. 是否接受单选确定性评分、简答异步 LLM 评分？
3. 是否接受独立 `practice` queue/worker 和 Practice Job，而不复用 course queue/job？
4. 是否接受生成和每次简答评分分别进行 external-processing acknowledgement？
5. 是否接受候选 step/search/call/token/time 预算？
6. 是否接受取消后保留简答 Attempt 但不提交 Feedback，用户可重试或删除？
7. 是否接受建议的 AgentRun/tool trace 与敏感字段排除边界？

以上 7 项已于 2026-07-16 获人工接受。

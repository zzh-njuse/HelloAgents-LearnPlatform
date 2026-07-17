# Spec 001：课节练习、作答与可信反馈

状态：已于 2026-07-16 通过人工 Gate，可生成 GLM 实现任务包

日期：2026-07-16

## 1. 评审结论摘要

本 Spec 建议 Stage 4 Slice 1 只建立 Reader 内的最小练习闭环：用户针对当前发布课节显式生成一个独立 Practice Set，完成单选题或简答题，得到可追溯反馈，重新作答并查看或删除历史。

第一版不写掌握度、薄弱点、复习队列或长期 Memory，也不引入 Skill、MCP 或自主多 Agent。单选题由服务端确定性评分；简答题由版本化 rubric 约束的 LLM 评估，并始终标注为 AI 反馈。任何生成或评分失败都不得回退为无证据题目、固定分数或伪成功结果。

## 2. 已验证事实、本次建议与待选项

| 类型 | 内容 |
|---|---|
| 已验证事实 | Reader 已有稳定 Course/Lesson Version；课程固定来源快照；产品已有任务、引用、取消、重试、trace 和删除模式 |
| 已验证事实 | prototype Assessor 无产品事实、无 citation ledger，且存在固定 50 分 fallback，不能直接复用 |
| 本次建议 | 第一版只做当前发布 Lesson Version 的 lesson-scope Practice Set |
| 本次建议 | 题型为 `single_choice` 与 `short_answer`；每组默认 5 题，允许 1-10 题 |
| 本次建议 | 每次重新生成创建新 Practice Set，不覆盖历史题目和 Attempt |
| 本次建议 | 单选同步确定性评分；简答异步 AI 评估，按 rubric 返回 verdict、分数与反馈 |
| 待人工选择 | 是否接受上述题型、数量、预算、外部处理确认和删除粒度 |

## 3. Goal / Context / Constraints / Done when

| 项目 | 内容 |
|---|---|
| Goal | 用户在 Course Reader 内完成“生成练习 -> 作答 -> 反馈 -> 重做/查看历史”的第一条可信闭环 |
| Context | Stage 3 已完成版本化课程、Lesson Citation、受控 Agent、任务队列、删除和最小 trace；尚无练习产品事实 |
| Constraints | Postgres 权威；证据固定到课程来源快照；用户答案不进日志；失败不伪造成功；不提前写 mastery/memory |
| Done when | 单选和简答端到端可用，题目/引用/作答/反馈可追溯，删除和失败路径可验证，固定 eval 与 Chrome smoke 通过 |

## 4. 术语

| 术语 | 含义 |
|---|---|
| Practice Set | 一次成功生成的、绑定精确 Lesson Version 的不可变练习集合 |
| Practice Item | 集合中的一道题，包含题型、题干、选项（如适用）、隐藏 answer spec、rubric 和证据引用 |
| Attempt | 用户对某一道题的一次不可变提交；重新作答创建新 Attempt |
| Feedback | 对一个 Attempt 的正式结果；包含 verdict、可选分数、rubric 结果、反馈块和已校验引用 |
| Generation Job | 显式生成 Practice Set 的异步权威任务 |
| Grading Job | 简答 Attempt 的异步评估任务；单选题不需要 LLM Grading Job |
| Answer spec | 服务端评分所需的正确选项、参考要点和允许变体；提交前不可公开 |
| Rubric | 版本化评分标准；简答评估必须逐项返回结果 |

## 5. 用户路径

### 5.1 进入练习

1. 用户进入当前激活 Course Version 的一个已发布课节。
2. Reader 提供稳定的“正文 / 练习”切换，不把 Practice 做成独立营销页或塞进 Tutor 对话流。
3. “练习”默认列出该精确 Lesson Version 已成功生成的 Practice Set；历史 Lesson Version 的集合不会混入。
4. 若尚无集合，显示明确空状态和“生成练习”命令。

页面采用已确认的三栏关系：左侧继续显示课节目录；中间主内容区通过“正文 / 练习”切换；右侧辅助栏通过“Tutor / 练习记录”切换。完整练习始终使用中间主内容区，不塞入狭窄右栏。用户在右侧打开 Tutor 时，中间当前题号、未提交答案和练习进度不得丢失。

### 5.2 生成 Practice Set

1. 用户选择题目数量、难度和输出语言；默认 5 题、标准难度、沿用课节语言。
2. 第一版题型固定混合单选和简答；数量为 1 时由服务端选择一种，数量至少 2 时至少包含一道简答和一道单选。
3. Web 明确提示：生成会把当前课程来源中检索到的片段发送给已配置 generation provider。
4. 用户确认后创建 Generation Job；任务身份必须显示课程和课节名称、题数和状态。
5. 同一 Lesson Version 可以生成多个独立集合用于比较或重复练习；“重新生成”创建新集合，不替换旧集合。
6. 只有完整 artifact 通过 schema、预算、citation 和来源快照校验后，Practice Set 才原子可见。

### 5.3 作答与反馈

1. 用户逐题作答，在最后一题统一交卷；存在未答题时列出页面题号并确认是否提前交卷。Web 将整份答卷拆成各题不可变 Attempt 提交；提交前 API 不能返回正确答案、reference answer、rubric 或解析。
2. 单选题在服务端确定性比较稳定 option key，同一事务创建 Attempt 与 Feedback。
3. 简答题提交前明确提示用户答案会发送给配置的 provider，并要求显式确认；提交后创建 Attempt 和 Grading Job。
4. 简答 Feedback 显示“AI 反馈”，包含 verdict、0-100 分、rubric 分项、改进建议和可用引用；不得冒充人工教师或官方考试成绩。
5. 用户可以重新作答；每次提交创建新 Attempt，旧 Attempt 和 Feedback 保持不变。
6. 用户可以查看该题的历史 Attempt，并删除某次作答；删除后答案和对应 Feedback/Grading trace 不再可读。

### 5.4 删除

- 用户可以删除整个 Practice Set；集合立即从默认列表隐藏并阻止新 Attempt，随后清理题目、引用、Attempt、Feedback、Job 和相关 trace。
- 删除单次 Attempt 不删除题目或其他 Attempt。
- 删除 Course 或 Workspace 时，Practice 数据进入其现有删除权威；删除 Practice Set 不删除 Course、Lesson 或来源资料。

## 6. 范围

### 包含

- 当前激活 Course Version、当前发布 Lesson Version 的 lesson-scope Practice；
- 单选题与简答题；
- 1-10 题的独立 Practice Set；
- 中文与英文输出；
- 异步生成、简答评分、取消、重试和运行摘要；
- Practice Set/Attempt 历史与删除；
- 固定离线 eval、真实 provider 人工观察和 Chrome smoke。

### 明确不做

- course-wide 综合练习、跨课程练习或自动每日练习；
- 多选、判断、填空、代码执行、数学工具、文件上传答案或外部判题；
- 提示层级、苏格拉底教学或其他 Skill 产品化；
- Learning Event、Mastery、Weakness、Review Queue 和长期 Memory；
- MCP、网页搜索、自主多 Agent、认证、多租户和金额成本；
- 人工教师批改、同伴互评、证书或排名。

## 7. 内容与评分合同

### 7.1 单选题

- 2-6 个选项，每个选项有稳定、无语义泄露的 key。
- 只能有一个正确选项；题干、选项和正确答案必须由同一组有效证据支持。
- 每个选项都必须生成隐藏的、带引用的 option rationale；提交后既解释正确答案为什么成立，也解释用户所选错误项为什么不成立。
- Feedback 至少包含 `correct|incorrect`、用户所选项、正确选项、上述解释、资料位置和引用；分数为 100 或 0。
- 正确 option key 只由服务端读取，不接受模型在评分阶段重新判断。

### 7.2 简答题

- 预期用户使用短文本作答；第一版答案最大 8,000 字符。
- Rubric 包含 1-5 个 criterion，每项有稳定 key、描述、权重和证据引用；权重合计 100。
- 评估输出包含 `correct|partially_correct|incorrect|ungradable`、0-100 整数分、逐项结果和简短改进建议。
- Feedback 必须指出具体错误或遗漏、解释正确思路，并给出一份简洁的参考讲解；不能只返回分数和笼统评语。
- `ungradable` 不得伪造数值分，Feedback 解释证据不足、答案超出资料或评估失败原因。
- 评分只能使用该 Practice Item 已验证的 answer spec、rubric 和 evidence ledger，不在评分阶段扩大检索或调用外部工具。
- 结构或引用修复最多一次；仍不合法则 Grading Job 失败，不提交 Feedback。

### 7.3 引用

- Practice Item Citation 必须属于同一 Workspace 和绑定 Course Version 的精确 source snapshot。
- 模型只返回临时 citation key；服务端从 evidence ledger 回填 document/version/chunk 身份。
- Feedback 只能引用该 Item 已有的证据 ledger，不接受新的 document/chunk ID。
- 用户可读位置继续使用“文件名 > 章节路径 > 第 N-M 页”；来源失效时显示不可用，不猜测页码。

## 8. 状态与失败行为

### 8.1 Job 状态

沿用现有任务语义：`queued`、`running`、`retry_wait`、`queue_failed`、`cancel_requested`、`canceled`、`succeeded`、`failed`。

### 8.2 Attempt 状态

- 单选：事务内从提交直接进入 `succeeded`。
- 简答：`grading -> queue_failed|retry_wait|succeeded|failed|cancel_requested|canceled`。
- queue 不可用时保留 Attempt，标记 `queue_failed` 并允许重试同一 Grading Job。
- Attempt 一旦提交，answer payload 不可原地修改。

### 8.3 失败矩阵

| 场景 | 结果 |
|---|---|
| Lesson 未发布、不是当前发布版本或 Course 非当前激活版本 | 创建生成 Job 前 409/422，不隐式切换版本 |
| Course `source_degraded` 或来源快照失效 | 历史 Set、Attempt 与 Feedback 只读；禁止生成新集合、提交新 Attempt 或重新评分，返回 `source_snapshot_stale` |
| 证据不足 | `insufficient_evidence`，不生成 fallback 题 |
| artifact/rubric/citation 非法 | 最多一次受控修复，仍失败则整体不提交 |
| provider 未配置/不可用/超时 | Job 失败或按策略 retry，不生成半成品 |
| 重复 Idempotency-Key 与相同 payload | 返回原资源/Job |
| 相同 key 与不同 payload | 409 `idempotency_key_conflict` |
| 用户删除 Set/Course/Workspace 或请求取消 | worker 停止；晚到结果不得复活资源 |
| 简答评分无效、答案超范围或证据不足 | `ungradable` 或 Job 失败；不得固定给 50 分 |
| 评分失败后重试 | 重用同一 Attempt 和 Job，不创建重复正式 Feedback |

## 9. API 草案

所有路径先约束 Workspace，并验证 Course/Course Version/Lesson/Lesson Version 的完整归属链。

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/workspaces/{workspace_id}/courses/{course_id}/versions/{course_version_id}/lessons/{lesson_id}/versions/{lesson_version_id}/practice-sets` | 创建 Generation Job |
| `GET` | 同上 `/practice-sets` | 列出该 Lesson Version 的可见集合 |
| `GET` | `/workspaces/{workspace_id}/practice-sets/{set_id}` | 读取集合与安全题目投影 |
| `DELETE` | `/workspaces/{workspace_id}/practice-sets/{set_id}` | 删除集合及派生事实 |
| `GET` | `/workspaces/{workspace_id}/practice-jobs/{job_id}` | 查询任务状态 |
| `POST` | `/workspaces/{workspace_id}/practice-jobs/{job_id}/cancel` | 请求取消 |
| `POST` | `/workspaces/{workspace_id}/practice-jobs/{job_id}/retry` | 重试可重试 Job |
| `POST` | `/workspaces/{workspace_id}/practice-items/{item_id}/attempts` | 提交单次答案 |
| `GET` | `/workspaces/{workspace_id}/practice-items/{item_id}/attempts` | 查看该题作答历史 |
| `GET` | `/workspaces/{workspace_id}/practice-attempts/{attempt_id}` | 读取 Attempt 与 Feedback |
| `DELETE` | `/workspaces/{workspace_id}/practice-attempts/{attempt_id}` | 删除单次作答及派生事实 |

创建与提交命令必须使用 `Idempotency-Key`。列表默认按创建时间倒序并设置有限上限；第一版不提供任意导出或原始 prompt/日志下载。

## 10. 安全读取投影

提交前 Practice Item API 允许返回：题型、题干、选项、难度、序号和用户可读引用。

提交前禁止返回：正确 option、reference answer、rubric、provider/model、prompt、evidence/chunk 正文、内部路径、tool input、input hash 或原始响应。

Feedback API 只在 Attempt 属于当前 Workspace 且已正式提交后返回该 Attempt 的 verdict、分数、rubric 分项、反馈块和引用。其他 Attempt 的答案或隐藏评分材料不能通过猜测 ID 读取。

## 11. 候选预算

以下是为可测性和失败收敛提出的第一版默认值，待人工 Gate 接受：

| 项目 | 候选值 |
|---|---|
| 每个 Practice Set | 默认 5 题，最少 1、最多 10 |
| Exercise Author | 最多 6 step、3 次 evidence search、6 次 provider call |
| 生成 evidence | 最多约 24K token |
| 生成总输出 | 最多约 12K token |
| 生成 wall time | 最多 10 分钟 |
| 简答用户答案 | 最多 8,000 字符 |
| Answer Grader | 不检索；最多 2 次 provider call（初次 + 一次修复） |
| 评分 evidence/rubric 输入 | 最多约 12K token |
| 评分输出 | 最多约 3K token |
| 评分 wall time | 最多 3 分钟 |

预算耗尽必须以稳定错误结束，不能截断后提交。金额成本仍不在 Slice 1 展示。

## 12. 隐私与外部处理

- 生成只发送绑定来源快照中检索到的必要片段，不发送整份文件。
- 简答评分只发送当前题目的必要 rubric/evidence 和该次用户答案。
- 生成与每次简答提交均记录显式 external-processing acknowledgement；单选确定性评分不需要外部调用。
- 用户答案、正确答案、reference answer、rubric、完整 prompt、evidence 正文和 provider 原始错误不得进入普通日志或脱敏运行摘要。
- AgentRun 可以记录角色、状态、step、token、耗时和稳定错误码；不得公开题目、答案或评分细节。
- 固定 eval 只使用公开或脱敏 fixture，不提交真实用户答案。

## 13. 验收与 eval

### 自动化硬门禁

- Workspace/Course/Lesson Version 归属和 source snapshot 隔离 100%；
- 生成 artifact、rubric 和 citation schema 通过率 100%；
- 提交前 answer spec/rubric 不泄露；
- 单选评分确定性；简答评分逐项满足 rubric；
- 无证据、未知 citation、取消、预算耗尽和晚到结果不提交半成品；
- 幂等创建/提交/重试，queue failure 可恢复；
- 删除 Attempt/Set/Course/Workspace 后不可读取用户答案和 Feedback；
- 中英文题目与反馈保持请求语言。

### 观察指标

- 题目可回答性、歧义率、难度匹配、选项干扰质量；
- rubric 覆盖、Feedback 清晰度、可行动性和引用覆盖；
- 生成/评分 token、调用数、延迟和失败分布。

观察指标第一版不武断设置通用硬阈值；真实 provider 结果经人工评分后形成基线。

### 人工 Chrome smoke

- 在一门含可靠引用的课程中生成一组中/英文练习；
- 验证任务身份、队列、取消/重试和多个集合切换；
- 验证提交前不泄露答案，单选即时反馈，简答异步 AI 反馈；
- 重新作答并查看历史，删除 Attempt 和 Practice Set；
- 验证窄视口、长题干、长选项、引用和错误状态不重叠；
- Network 响应不包含 prompt、evidence 正文、答案 key、内部地址或绝对路径。

## 14. 实现交接

本 Spec 与 ADR 未经人工接受前，不生成 GLM 实现任务包。接受后由 Codex 按 `GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md` 拆分 migration/ORM、API/service/worker、domain artifacts/tests、Web 和复验批次；GLM 不自行改变本合同。

## 15. 人工 Gate（已接受）

1. Slice 1 是否只做当前激活 Course Version 的当前发布 Lesson Version，course-wide Practice 留后续？
2. 第一版题型是否为单选题和简答题？
3. 是否接受每组默认 5 题、范围 1-10，重新生成创建独立集合？
4. 单选是否确定性评分；简答是否显示 AI 反馈、0-100 分、verdict 和 rubric 分项？
5. 是否接受提交前严格隐藏 answer spec、reference answer 和 rubric？
6. 是否要求生成练习和每次简答评分分别确认外部处理？
7. 是否允许查看并删除单次 Attempt，同时允许删除整个 Practice Set？
8. 是否接受 Slice 1 不写 Learning Event、Mastery、Review Queue 或 Memory？
9. 是否接受第 11 节的数量与运行预算？
10. 是否接受本 Spec 的 API、失败、隐私、eval 和人工 smoke 范围？

以上 10 项以及“左侧课节目录 / 中间正文与练习 / 右侧 Tutor 与练习记录”的前端结构，已于 2026-07-16 获人工接受。实现不得自行改成右侧窄栏内完成练习，也不得跳过提交后错误解释和资料位置。

# ADR 001：练习快照、作答与删除权威

状态：已于 2026-07-16 通过人工 Gate

日期：2026-07-16

## 1. 决策摘要

Postgres 是 Practice Set、Practice Item、Citation、Attempt、Feedback 和 Practice Job 的唯一权威事实来源。每次成功生成创建一个新的不可变 Practice Set snapshot；题目、answer spec 和 rubric 不原地改写。重新生成创建新 Set，重新作答创建新 Attempt。

第一版不建立通用 Concept、Learning Event、Mastery、Review Item 或 Memory 表。Practice history 只记录发生了什么，不提前推断用户掌握度。

## 2. 背景

Stage 3 已证明课程和 Lesson Version 必须是不可改写快照，否则生成重试、引用和历史阅读会互相覆盖。练习还增加了两个风险：提交前不能泄露正确答案；用户答案是敏感内容，必须能查看和删除。

prototype 的 dataclass 和本地 UserModel 无法提供版本、workspace 隔离、幂等、删除、引用或迁移合同，因此不能成为产品事实。

## 3. 决策

### 3.1 建议实体

| 表 | 权威含义 |
|---|---|
| `practice_sets` | 一次成功生成的稳定集合；固定 Workspace/Course/Course Version/Lesson/Lesson Version、语言、难度和生成配置摘要 |
| `practice_items` | Set 内不可变题目；包含题型、题干、选项、隐藏 answer spec 和 rubric |
| `practice_item_citations` | Item 到 Course Version source snapshot 内 Document Chunk 的规范化映射 |
| `practice_attempts` | 用户对一个 Item 的一次不可变答案提交和评分状态 |
| `practice_feedback` | 一个 Attempt 的正式 verdict、可选分数、rubric 结果和反馈块 |
| `practice_jobs` | `generate_set` 或 `grade_attempt` 的权威异步任务、预算、幂等和失败事实 |
| `practice_job_sources` | Generation Job 创建时固定的精确 Document Version 来源 |

具体列名由实现任务包细化，但必须满足本 ADR 的归属、唯一性、隐藏字段和删除约束。

### 3.2 Snapshot 与版本

- Practice Set 只在完整生成成功后原子创建并对用户可见。
- Practice Item、answer spec、rubric 和 citation 创建后不可原地编辑。
- “重新生成”创建新 Set，不增加旧 Set 的可变 revision，也不迁移旧 Attempt。
- Set 固定生成时的 Course/Lesson Version；课程或课节后续激活新版本不改变历史 Set。
- Set 本身就是版本化练习 artifact，因此 Slice 1 不额外建立空壳 `exercise_versions` 表。
- 若未来需要人工编辑题目或发布流程，再以新 ADR 增加稳定 Exercise 身份和显式版本，不提前设计。

### 3.3 Attempt 与 Feedback

- Attempt 保存精确 `practice_item_id`、workspace、递增 ordinal、answer payload、状态、提交时间和 external-processing acknowledgement（如适用）。
- Answer payload 按题型使用严格 schema：单选只接受 option key，简答只接受长度受限文本。
- Attempt 创建后答案不可修改；重新作答创建新 ordinal。
- 单选 Feedback 与 Attempt 同事务提交。
- 简答先提交 Attempt 和 Grading Job，只有完整评估通过后才创建一份正式 Feedback。
- 同一个 Attempt 最多有一个正式 Feedback；worker retry 不得重复创建。
- Feedback blocks 中的 citation key 必须在该 Item 的 citation ledger 中，服务端不接受任意 document/chunk ID。

### 3.4 隐藏评分材料

- `answer_spec`、各选项 rationale、reference answer、参考讲解和 rubric 是 Postgres 产品事实，但属于服务端评分投影。
- 普通 Item read schema 明确排除这些字段，不能直接序列化 ORM。
- 只有 Attempt 已提交后，Feedback 投影才能返回允许公开的 rubric 分项和参考解释；仍不得返回内部 prompt 或 evidence 正文。
- 管理或 debug API 不在 Slice 1 提供原始隐藏材料下载。

### 3.5 归属与约束

- 所有表保留 `workspace_id`，所有服务查询先约束 Workspace。
- Set 的 Course/Course Version/Lesson/Lesson Version 必须形成同一条有效归属链。
- Item 只能属于一个 Set；Attempt 只能属于一个 Item；Feedback 只能属于一个 Attempt。
- Citation 的 document/version/chunk 必须属于 Set 固定 Course Version 的 source snapshot。
- Generation Job 的 source rows 在创建时固定；worker 不重新解析“当前资料版本”。
- 幂等唯一键至少覆盖 Workspace + Idempotency-Key，并结合 canonical request hash 检测冲突。

## 4. 生命周期与删除

### 4.1 Practice Set 删除

1. API 锁定 Set，将其标记为 `deleting`，立即从默认列表隐藏并阻止新 Attempt。
2. 请求排队/运行中的 generation/grading Job 取消；迟到 worker 在最终提交前重新检查 Set/Course/Workspace 权威状态。
3. cleanup 按 Feedback -> Attempt -> Item Citation -> Item -> Job trace/Job -> Set 的依赖顺序清理。
4. 清理失败不恢复 Set 可见性；由 retry/reconciler 继续。

### 4.2 Attempt 删除

- 删除单次 Attempt 是范围受限操作：先使其不可读，再删除 Feedback、Grading Job trace、Job 和 answer payload。
- 其他 Attempt、Item 和 Set 不受影响；ordinal 允许留空，不重排历史。
- 运行中的 Grading Job 必须取消，晚到结果不能重建 Feedback。

### 4.3 上游删除

- Course 删除必须先清理全部 Practice 派生事实，再删除 Course Version/Lesson 事实；不删除来源资料。
- Workspace 删除把 Practice 纳入现有清理图和 reconciler。
- 来源删除不级联删除已生成 Set；Set 保留历史题目、Attempt 与 Feedback，但引用显示不可用，整个历史 Set 进入只读状态。禁止基于降级来源生成新 Set、提交新 Attempt 或重新评分。
- 当前没有单独删除 Lesson Version 的产品命令；未来新增时必须处理 Practice 依赖。

## 5. 数据保留与敏感边界

- 用户答案和 Feedback 正文保存在 Postgres，因为它们是用户明确要求查看的产品事实。
- 它们不复制到 Qdrant、普通日志、AgentRun 安全摘要、eval report 或本地 JSON。
- Qdrant 不为 Slice 1 建立 exercise/memory collection；练习检索仍从 Course source snapshot 获取证据。
- API、日志和错误只返回稳定业务错误码，不返回数据库连接、provider 原文或绝对路径。

## 6. 不采用的方案

### 方案 A：把整组题目和所有作答存为 Lesson Version 上的一个 JSON

拒绝。无法独立幂等提交、查询历史、隐藏评分材料、删除单次答案或建立稳定外键。

### 方案 B：直接复用 `AssessmentQuestion` / `AssessmentResult`

拒绝。它们是进程内 prototype dataclass，没有产品归属、版本、citation 和删除合同。

### 方案 C：先建立通用 Concept/Mastery/Memory schema

拒绝。Slice 1 尚未证明推断规则；提前建表会让后续 Slice 被未经验证的模型锁定。

### 方案 D：题目原地编辑，Attempt 自动跟随最新题目

拒绝。历史答案会失去评分上下文，无法审计当时用户回答的具体题目。

### 方案 E：来源删除时级联删除所有练习历史

拒绝。Practice Set 是独立用户成果；沿用 Stage 3 `source_degraded` 语义更可解释。删除 Course/Set 时才清理练习。

## 7. 影响

### 正向

- 历史题目、作答和反馈稳定可追溯；
- 重新生成和重新作答不会覆盖用户历史；
- 提交前答案泄露边界可以由 response schema 自动测试；
- Slice 2 可以从可信 Attempt/Feedback 形成 Learning Event，而不是从日志或 prompt 猜测。

### 代价

- 增加多个 Postgres 表、migration、删除顺序和服务层投影；
- answer payload 与评分材料需要更严格的日志和 API 审查；
- 来源降级后需要在 Set 引用展示、生成入口和作答入口保持一致的只读状态。

## 8. 验证要求

- migration 全量 upgrade、downgrade/upgrade 和真实 Postgres FK/唯一约束；
- 跨 Workspace/Course/Lesson Version 组合全部拒绝；
- Set/Item 不可变、Attempt ordinal、幂等和单 Feedback 约束；
- answer spec/rubric 在提交前的 API 与 Web Network 中缺失；
- Attempt/Set/Course/Workspace 删除、并发评分和晚到 worker；
- source_degraded 时历史 Set/Attempt/Feedback 可读，新生成、新 Attempt、重做和重新评分均禁止，citation 不伪造可用。

## 9. 人工 Gate（已接受）

1. 是否接受每次生成创建独立、不可变 Practice Set，而不在 Slice 1 建立 `exercise_versions`？
2. 是否接受 Attempt 不可修改，重新作答创建新 Attempt？
3. 是否接受用户可删除单次 Attempt 和整个 Practice Set？
4. 是否接受来源删除后保留历史 Set、引用标记不可用，并禁止新生成？2026-07-16 进一步确认：降级 Set 完全只读，也禁止新 Attempt、重做和重新评分。
5. 是否接受 Slice 1 不创建 Concept/Learning Event/Mastery/Review/Memory 表？
6. 是否接受建议的七类表及其 Postgres/Qdrant/Redis 权威边界？

以上 6 项已于 2026-07-16 获人工接受。

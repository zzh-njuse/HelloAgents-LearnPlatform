# ADR 004：用户管理的长期学习 Memory

状态：原决策已于 2026-07-17 通过人工 Gate；Lesson Completion 增量决策已于 2026-07-18 获得人工接受

日期：2026-07-17

## 背景

Framework/Academic Companion 的 Memory 以通用 content/metadata、本地 SQLite、Qdrant 或 Neo4j 保存对话与摘要。产品需要的是可见、可纠正、可删除、有来源且能控制外发的学习状态，不能把通用 Memory adapter 或 Tutor history 直接变成用户画像。

## 决策

第一版 Learning Memory 只保存由 `confirmed` Weakness 自动、确定性建立的目标级记录。Postgres 是唯一权威；自动建立不等于自动 LLM 摘要，不建向量索引、不默认启用 Neo4j。

## 数据模型

| 表 | 关键字段 |
|---|---|
| `learning_memories` | workspace/course/lesson/target/weakness、kind=`weakness`、status、display_text、created/confirmed/last_supported_at、revision |
| `learning_memory_sources` | memory、learning_event；组合唯一，只保存引用，不复制答案或 feedback |
| `learning_memory_revisions` | memory、revision、action=`auto_created|edited|reconfirmed|paused|archived|conflicted`、安全前后 hash、created_at |
| `learning_memory_policies` | workspace 唯一、`tutor_use_enabled`、updated_at |

公开 API 返回目标名称、用户说明、状态、来源题目/课节的安全定位、证据数量和时间，不返回历史答案、rubric、feedback 正文或 prompt。

## 创建与编辑

- 只有 `confirmed` Weakness 可以创建 Memory；同一 target 只允许一个未归档 Memory。
- Weakness 转为 `confirmed` 时，在同一投影事务中自动且幂等创建 Memory；重复事件、worker delivery 或全量重算不得创建副本。
- 默认说明由确定性模板生成，例如“我需要继续巩固：{target title}”；不调用 LLM，也不复制历史答案、feedback 或证据正文。
- 用户编辑只改变 `display_text`，不改变 source event、mastery 或 weakness。
- 每次自动创建、编辑、重新确认、暂停和归档都写 revision；普通运行摘要只报告动作类型和状态。

## 状态

```text
active -> needs_review -> active | archived
   |          |
   +-> paused +-> deleted
   +----------------> archived
```

- `active`：可用于当前 target 的 Tutor 上下文。
- `needs_review`：证据冲突、source degraded、课节换版或 90 天无支持证据；停止 Tutor 使用。
- `paused`：用户暂时禁止使用；仍可管理。
- `archived`：保留用户历史但不使用。
- DELETE：硬删除 Memory、source links 和 revisions；不提供软删除回读。
- DELETE 同时在 Weakness 写入不含正文的 `memory_suppressed_at` 水位；旧 event 重放或全量重算不得重建 Memory。删除后的新负向 event 再次满足 confirmed 条件时才清除水位并自动建立新 Memory。

## 冲突与时间

- 后续 target 达到 `secure` 或 Weakness resolved 时，Memory 转 `needs_review`，不自动宣称用户已经掌握。
- 支持 source 删除后重算；若没有有效 source，Memory 硬删除。
- 90 天无新支持 signal 只标记 `needs_review`，不改变 mastery、不自动删除。
- 用户选择继续保留时写新 confirmation revision，并把 `last_supported_at` 与“用户确认时间”分开显示。

## Tutor 注入

- 自动创建与平台内部复习使用默认启用，不要求逐条人工确认。
- Tutor Policy 默认关闭，只控制是否将合格 Memory 发送给配置的外部 Tutor provider；用户在 Workspace 明确开启一次后才可供 Tutor 使用。
- 只选当前 Workspace/Course/Lesson 的 `active` Memory，最多 5 条、约 600 token。
- 注入内容仅为 target title、display text、状态和确认时间；不包含历史答案、feedback、rubric 或 evidence 正文。
- 选择是确定性关系查询，不做 embedding/向量搜索。
- Tutor Turn 的 trace 只记录使用数量和 memory ID hash，不记录 display text。
- 外部处理确认必须明确：开启 Workspace Memory 使用后，学习 Memory 摘要可能随问题发送给配置的外部 AI。

## 删除权威

- 删除 Attempt：移除 source link并重算；没有有效 source 时删除 Memory，否则可能转 `needs_review`。
- 删除 Course：删除目标关联 Memory，不保留“已删除课程”的薄弱点文本。
- 删除 Workspace：硬删除 policy、memory、source 和 revision。
- 删除 Memory 不反向删除 Attempt、Feedback、Mastery 或 Weakness；Weakness 仅保留阻止旧证据复活 Memory 的安全时间水位。
- Stage 4 最终人工删除 smoke 必须验证 Network/API/Tutor 均不能回读已删除 Memory 文本。

## 成本与安全

- 创建、冲突、过期和选择均为确定性逻辑，不产生 provider call。
- 只有 Tutor 使用 Memory 时增加 input token，硬上限约 600；provider 未报告 usage 时继续遵守 Stage 3 `null` 语义。
- Memory 文本不进入日志、AgentRun summary、Qdrant 或 Redis payload。
- 当前没有 authenticated user；Memory 属于 Workspace，不应在 UI 中称为跨账号“个人画像”。

## 未采用方案

- 要求用户逐条批准 confirmed Weakness 才创建 Memory：交互负担过高，且把系统整理职责推给用户。
- 自动创建即自动外发：Memory 建立与外部 Tutor 使用是不同权限，外发仍需 Workspace 级明确开启。
- 保存 Tutor 对话摘要或完整答案：隐私和删除风险过高。
- 通用 key/value preference memory：第一版缺少可信来源与使用场景。
- Qdrant semantic retrieval：target 关系已足够，额外索引增加删除和泄漏面。
- 自动覆盖旧 Memory：会隐藏冲突，不利于用户纠正。

## 增量提议：学习进度事实与弱点 Memory 分离

`lesson_completed` 不应伪装成 `weakness` Memory，也不进入 mastery 投影。建议以独立的版本级完成事实保存，由 Tutor 上下文装配层把两类安全信息组合为“学习画像”：

- Weakness Memory 回答“哪些目标需要继续巩固”。
- Lesson Completion 回答“用户明确完成过哪些课节版本”。
- 两者都不能单独证明掌握；掌握度仍只来自已评分 Attempt。
- Tutor 不得简单复述上下文列表，而应按用户问题选择、综合并解释相关信息；不得按固定问句硬编码输出。

这样可以扩充 Memory 的实际用途，同时保持事实语义、删除和重算边界清晰。已接受的增量决策为：完成事实绑定 Lesson Version、允许撤销、最多向 Tutor 提供当前范围最近 10 条，并与 Weakness Memory 共用外发开关和约 600 token 总预算。

## 生效条件

用户已于 2026-07-17 接受自动建立、用户管理、Tutor 外发单独控制、90 天复核和删除行为，本 ADR 生效。

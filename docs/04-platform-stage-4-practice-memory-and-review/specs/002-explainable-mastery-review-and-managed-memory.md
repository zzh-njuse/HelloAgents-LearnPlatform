# Spec 002：可解释掌握度、复习队列与可管理学习 Memory

状态：原合同已于 2026-07-17 通过人工 Gate；Lesson Completion 增量合同已于 2026-07-18 获得人工接受

日期：2026-07-17

## 1. 目标

把 Practice 的确定性结果和 rubric 分项转换为可解释的学习信号，为用户提供“为什么需要复习、该复习什么、何时再次验证”的队列，并在薄弱点达到确认阈值后自动建立可查看、纠正、停用和删除的长期学习 Memory。

第一版不使用 LLM 推断掌握度，不把 Tutor history 自动升级为 Memory，也不引入 Skill、MCP、Neo4j 或产品内多 Agent。

## 2. 核心名词

| 名词 | 指代 |
|---|---|
| Learning Target | 某个 Lesson Version 内稳定、可引用的学习目标；新课节版本拥有新 target 身份 |
| Learning Event | 已评分 Attempt 的不可变学习事实；复习操作另存 Review Action，不混入 mastery evidence |
| Mastery Signal | 从一个已评分 Attempt 确定性派生出的目标级正向、部分或负向证据 |
| Mastery State | 对目标信号的可重算投影，只显示分档、证据数量与最后验证时间，不冒充精确能力百分比 |
| Weakness | 基于负向证据形成的可解释候选或已确认薄弱点 |
| Review Item | 针对一个 Weakness 的可操作复习队列项 |
| Learning Memory | 系统根据已确认 Weakness 自动建立、由用户管理且可撤销的长期薄弱点记录；不是原始答案或对话摘要 |
| Lesson Completion | 用户在已发布课节正文末尾明确点击“学习完毕”形成的版本级学习进度事实；表示已完成阅读，不表示已经掌握 |

## 3. 用户闭环

1. Practice Feedback 提交后，平台生成目标级 Learning Event 和 Mastery Signal。
2. 用户在 Workspace 顶部看到“待复习 N 项”，进入 Review Queue。
3. 每个 Review Item 显示目标、当前分档、推荐原因、来源题目/课节、AI 评分标记和下一步。
4. 用户可以查看资料/反馈、标记“已复习”、稍后、跳过或开始一次新的验证练习。
5. “已复习”只改变队列状态，不提高 mastery；只有新的已评分 Attempt 能验证改善。
6. 初次负向证据可以立即产生“初步建议”，但不会成为稳定 Weakness 或长期 Memory。
7. 证据满足确认条件后，平台自动建立长期 Memory；用户不需要逐条确认，但可以查看和管理。
8. 用户可编辑 Memory 的显示说明、暂停其 Tutor 使用、归档或删除。
9. 新的相反证据、来源变化或课节新版本会把 Memory 标为“需要复核”，并停止自动进入 Tutor 上下文。
10. 用户读完已发布课节后可在正文末尾标记“学习完毕”；平台保存所完成的 Lesson Version，并可将安全的完成记录用于复习导航和 Tutor 个性化，但不提高 mastery。

## 4. 可见掌握度

第一版显示四档，不显示看似精确的 0-100 用户能力值：

| 分档 | 用户含义 |
|---|---|
| 证据不足 | 少于 2 次独立有效 Attempt，不能形成稳定判断 |
| 需要复习 | 有足够负向证据，已生成或维持 Review Item |
| 学习中 | 有混合或改善证据，但尚未满足稳定掌握条件 |
| 较稳固 | 至少 3 次独立 Attempt、跨至少 2 个 Practice Set，最近投影达到稳固阈值 |

每个分档必须同时展示：有效 Attempt 数、确定性/AI 信号构成、最后验证时间和“查看依据”。用户删除来源 Attempt 后，分档必须重新计算。

## 5. 抗单次污染

- 第一次负向信号只创建 `provisional` Weakness 和低承诺 Review Item，Mastery 仍显示“证据不足”。
- `confirmed` Weakness 至少需要 2 个不同 Practice Item 的负向信号，并使目标投影进入“需要复习”。
- 简答 AI criterion 信号权重低于确定性单选；`ungradable`、失败、取消和未答题不产生 mastery signal。
- 查看反馈、标记已复习、跳过和稍后不提高 mastery。
- Weakness 只有在后续至少 2 个不同 Item 的正向验证使投影达到“较稳固”时自动转为 `resolved`。
- 用户可将误判 Weakness 标为“不适用”；该操作不篡改历史信号，但关闭当前 Review Item。新的负向证据可以重新提出建议，并明确说明为何重开。

## 6. Review Queue

Review Item 状态：

```text
due -> reviewing -> awaiting_validation -> resolved
 |        |                 |
 +-> snoozed <--------------+
 +-> dismissed --(new negative evidence)--> due
```

- `due`：当前建议复习。
- `reviewing`：用户已打开资料、反馈或练习入口。
- `awaiting_validation`：用户标记已复习，默认 3 天后提醒验证。
- `snoozed`：用户选择 1/3/7/30 天后再提醒。
- `dismissed`：用户认为当前建议不适用；不删除证据。
- `resolved`：新的 Attempt 证据满足解决条件。

排序依次考虑：已到期、confirmed 优先于 provisional、最近负向证据、当前 Course/Lesson 上下文。排序规则完全确定性，不调用 provider。

## 7. 可管理 Learning Memory

第一版只支持 `weakness` Memory：

- `confirmed` Weakness 在同一投影事务中自动、幂等地建立 Memory；`provisional` Weakness 不得建立 Memory。
- 默认说明由确定性模板根据 target title 生成，不调用 LLM，不复制历史答案、feedback 或证据正文。
- 保存目标、用户可编辑说明、来源 Weakness、有效证据引用、状态和最后确认时间。
- 状态为 `active|needs_review|paused|archived`。
- Memory 默认参与平台内部的复习队列与学习状态展示。
- Workspace 提供“允许 Tutor 使用学习 Memory”开关，默认关闭；该开关只控制向外部 Tutor provider 发送 Memory，用户首次明确开启后才允许注入，关闭后保留自动生成与管理页面。
- 用户可以修改说明，但不能修改来源事实；修改产生 revision/audit event。
- 90 天没有新的支持证据时标为 `needs_review`，停止注入 Tutor，不自动删除。
- 后续证据与 Memory 冲突时标为 `needs_review`；用户可归档、更新说明或明确继续保留。
- 删除 Memory 是硬删除，并在对应 Weakness 上记录不含 Memory 正文的抑制水位；旧事件重放或全量重算不得立即复活它，只有删除后的新负向证据再次满足条件才可自动重建。
- 删除 Course 或 Workspace 时删除其目标关联 Memory 和抑制水位。

## 8. Tutor 使用边界

- 仅 `active`、当前 Workspace/Course/Lesson 可关联且未过期的 Memory 可进入 Tutor。
- 每 Turn 最多 5 条、合计最多约 600 input token；按当前 Lesson 精确匹配优先，不做向量检索。
- 只发送目标标题和用户确认说明，不发送历史答案、rubric、feedback 正文或原始 Learning Event。
- Tutor UI 显示“本次使用 N 条学习记忆”，并允许用户跳转管理。
- Tutor Session 的外部处理确认文案必须包含已确认学习 Memory 可能发送给外部 AI；关闭 Memory 使用后不得发送。
- 增量提议：同一开关同时控制向 Tutor provider 发送当前课程内的 Lesson Completion 安全摘要；只含课节标题、版本和完成时间，不含阅读时长、滚动轨迹或正文副本。

## 8A. 增量提议：课节完成事实

- 每个已发布 Lesson Version 的正式阅读内容末尾提供“学习完毕”按钮；未发布草稿不提供。
- 点击后创建幂等的 `lesson_completed` 用户动作，归属 Workspace/Course/Lesson/Lesson Version，并显示完成时间与“已完成”状态。
- 新课节版本发布后，旧版本完成事实保留为历史；新版本默认未完成，并明确提示内容已更新。
- Lesson Completion 只证明用户明确完成过该版本的学习流程，不生成 Mastery Signal，不改变 band，不确认或解决 Weakness。
- 删除 Course/Workspace 时删除完成事实；删除或替换来源不把旧完成事实冒充为当前完成。
- 允许撤销“学习完毕”；Tutor 每 Turn 最多携带当前范围最近 10 条完成记录，并与薄弱点 Memory 共用约 600 token 总预算。第一版不新增独立进度页。

## 9. 目标映射与旧数据

- 新 Lesson Version 的 learning objectives 建立稳定 `objective_1..N` target key。
- 新 Practice Item/rubric 必须声明 target key，并在生成 artifact 校验。
- 旧 Practice Item 不用 LLM 回填，统一映射到该 Lesson Version 的 `lesson_overall` 合成目标。
- 新课节版本不自动合并旧 target mastery；旧状态显示为历史，当前版本从新证据开始。

## 10. 删除与重算

- 删除 Attempt：删除其 Learning Event/Signal，重算受影响 target、Weakness、Review Item；无剩余证据的派生项删除。
- 删除 Practice Set：按全部 Attempt 执行相同重算。
- 删除 Course：硬删除其 targets、events、signals、mastery、weaknesses、review items 和 memories。
- 删除 Workspace：在现有权威删除图中硬删除全部 Slice 2 事实和队列任务。
- 来源 degraded：历史学习状态可读并标注来源变化，但不能从 degraded Set 产生新事件；关联 Memory 进入 `needs_review` 且不注入 Tutor。
- 全量重算使用 Postgres 权威事件；Qdrant/Redis 丢失不影响结果。

破坏性人工删除 smoke 继续按已接受决定统一放到 Stage 4 最终 Gate。

## 11. 成本与任务

- 信号计算、掌握度、Weakness、Review Queue 和 Memory 状态全部确定性，不新增 LLM/provider 调用。
- 新 Practice 生成和简答验证继续使用 Slice 1 原预算。
- Tutor Memory 注入只增加最多约 600 input token，不增加 provider call 数。
- 单个 Attempt 的投影在同一业务事务内完成；Workspace 全量重算使用 Postgres Job 和现有 practice queue 投递，不新增默认服务。

## 12. 候选 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/workspaces/{id}/learning-state` | Workspace/Course/Lesson 掌握度摘要 |
| GET | `/workspaces/{id}/learning-targets/{target_id}` | 分档与证据依据 |
| GET | `/workspaces/{id}/review-items` | 筛选 Review Queue |
| POST | `/workspaces/{id}/review-items/{id}/actions` | reviewing/reviewed/snooze/dismiss |
| POST | `/workspaces/{id}/learning-state/recompute` | 创建全量重算 Job |
| GET | `/workspaces/{id}/learning-jobs/{id}` | 查询重算状态 |
| GET | `/workspaces/{id}/learning-memories` | 列出 Memory |
| PATCH | `/workspaces/{id}/learning-memories/{id}` | 编辑、暂停、归档或重新确认 |
| DELETE | `/workspaces/{id}/learning-memories/{id}` | 硬删除 Memory |
| GET/PATCH | `/workspaces/{id}/learning-memory-policy` | 查看或关闭 Tutor 使用 |

## 13. Eval 与完成标准

Hard gates：

- workspace/course/lesson version 隔离 100%；
- 同一 Feedback 重放不产生重复 event/signal；
- 一次错误不形成 confirmed Weakness 或长期 Memory；
- ungradable/failed/canceled/未答题不降低 mastery；
- 删除 Attempt 后投影与 Review Queue 可重复重算；
- provisional Weakness 不创建 Memory；confirmed Weakness 自动且幂等创建一个 Memory；paused/needs_review 不进入 Tutor；
- 用户删除 Memory 后，旧事件重放和全量重算不复活正文，只有新的独立负向证据可以越过抑制水位；
- API 不返回历史答案、rubric、feedback 正文、prompt 或 provider 配置；
- Workspace/Course 删除图通过 Postgres 集成测试。

Observational gates：推荐理由可理解、队列排序有用、Memory 说明不夸大、窄视口与长文本可用。

## 14. 明确不做

- 自动把聊天、阅读时长、页面滚动或未答题解释为掌握度。
- 把“学习完毕”按钮解释为掌握证据或自动提高掌握度。
- 从 provisional Weakness、聊天、阅读行为或未评分事实自动创建 Memory。
- 创建偏好 Memory 或“已掌握”Memory。
- 用 LLM 生成 mastery、复习排序或冲突结论。
- 在 Slice 2 引入 Review Coach Agent、Skill、MCP、Neo4j、认证或多租户。

## 15. 人工 Gate 结论

以下合同已于 2026-07-17 获得人工接受：

1. 对用户显示分档而非精确 mastery 百分比。
2. 第一次错误可进入低承诺复习建议，但需要两次独立负向证据才确认 Weakness。
3. 标记已复习不加分，必须由新 Attempt 验证。
4. 长期 Memory 第一版只保存 confirmed weakness，并在达到阈值后自动、幂等创建；用户负责查看、编辑、暂停、归档和删除，而非逐条批准创建。
5. Memory 自动用于平台内部复习；向 Tutor 外部 provider 发送仍由默认关闭的 Workspace 开关单独控制。
6. 90 天无支持证据或发生冲突后转 `needs_review`，停止 Tutor 注入并等待用户复核。
7. Tutor 每 Turn 最多使用 5 条、约 600 input token Memory，并更新外部处理确认文案。
8. 旧 Practice Item 只映射 `lesson_overall`，不让 LLM 猜测历史 target。
9. 全量重算复用 practice queue，不新增 learning worker 服务。

## 16. 2026-07-18 增量 Gate（已接受）

1. 接受显式 Lesson Completion 作为长期学习进度事实，但不作为 mastery evidence。
2. 新课节版本发布后要求重新完成，新旧完成记录按版本保留。
3. 允许用户撤销 Lesson Completion，撤销只删除完成事实，不影响 mastery。
4. Tutor 外发开关同时覆盖最多 10 条当前范围 Lesson Completion 摘要，并与 Memory 共用约 600 token 总预算。

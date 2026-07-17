# Platform Stage 4 输入

状态：Stage 4 初始事实输入；Slice 1 已完成，当前 Slice 2 输入见 `SLICE_2_INPUTS.md`

日期：2026-07-16

## 可继承的产品事实

- Workspace、Document Version、Course Version、Lesson Version、Tutor Session/Turn、异步 Job 和 Agent trace 均已由 Postgres 持有权威状态。
- Course 和 Tutor 使用固定来源快照与 chunk citation；任何练习题、反馈或薄弱点若声称来自资料，也必须回读同一引用合同。
- Reader 已拥有当前 Course Version 和 Lesson Version 上下文；Tutor 已区分 lesson/course scope，并保持可删除的短期 Session history。
- 生成任务已有 Redis/RQ 投递、Postgres 权威状态、幂等、取消、重试、lease、reconciler、预算和最小 trace 模式。
- 固定离线 eval 已覆盖生成、scope、citation、拒答、取消、预算和语言一致性，可扩展但不能被真实 provider 单次观感替代。
- Workspace 删除已定义跨资料、课程、Tutor、trace、索引和存储的清理顺序；Stage 4 新事实必须进入同一删除权威。

## 已接受且不能混淆的边界

- Tutor Session history 是短期 context，不自动升级为长期 Memory。
- 产品 Memory 必须可查看、纠正和删除，并能解释来源；隐藏 prompt、本地 JSON 或无来源摘要不是产品 Memory。
- Postgres 是练习、作答、反馈、掌握度、复习计划和 Memory 的候选权威事实来源；Redis 仍只负责非权威队列。
- 当前产品没有认证和多租户 membership。Stage 4 不应在没有独立 Spec/ADR 时顺带建立 SaaS 权限体系。
- 不把 `data/cs_fundamentals`、`data/leetcode` 或 `academic_companion` prototype schema 当作产品合同；它们只能提供公开 eval 样本或能力参考。
- Skill、MCP 和自主多 Agent 仍不是 Stage 4 默认前提。只有证明独立学习价值并完成相应合同后才可进入范围。

## Stage 4 首轮分析必须回答

1. 最小用户闭环是什么：按课节生成练习、用户作答、即时反馈、错题保留和复习推荐应如何串联？
2. Exercise、Attempt、Rubric、Feedback、Learning Event、Mastery、Weakness 和 Review Item 分别指什么，哪些必须版本化？
3. 练习题来自 Course Version、Lesson Version 还是固定来源快照；课程重新生成或课节激活新版本后，既有作答如何保持可解释？
4. 客观题、主观题和开放题分别如何评分；模型评分何时必须带 rubric、引用、置信度或人工确认？
5. 证据不足、题目有歧义、用户答案超出资料、评分失败或 provider 不可用时如何收敛，哪些结果不得提交？
6. 掌握度是可见事实、推断值还是推荐信号；更新规则、衰减、冲突、纠正、删除和重算如何定义？
7. 哪些学习事件有资格提升为长期 Memory；用户如何查看、纠正、删除或禁止某类记忆？
8. Review Queue 的推荐理由如何展示，如何防止单次错误答案永久污染薄弱点和复习计划？
9. 生成、评分、重试和复习分别需要什么任务预算、幂等键、取消语义、trace 和 eval？
10. Workspace、Course、Lesson、Tutor Session 或资料删除时，练习、作答、掌握度、复习项和 Memory 如何清理或去标识？

## 建议的 Spec/ADR 拆分顺序

1. 先写最小练习与作答 Spec：限定 Reader 内的生成、作答、反馈和错题用户路径，不同时实现完整 Memory。
2. 写练习事实与版本 ADR：定义 Exercise/Attempt/Rubric/Feedback 的 Postgres 权威、引用快照、幂等和删除。
3. 再写掌握度与复习 Spec：明确用户可见的薄弱点、推荐理由和复习操作。
4. 写 Learning Event、Mastery 与 Memory ADR：定义推断、提升、纠正、删除、过期和重算边界。
5. 最后决定是否需要独立 Exercise Agent 或 Review Coach；不得先以多 Agent 形式替代产品合同。

四切片方向已归档为 [Stage 4 四切片方向计划](STAGE_4_SLICE_PLAN.md)：Slice 1 练习/作答/反馈，Slice 2 掌握度/复习/Memory，Slice 3 教学 Skill，Slice 4 受控 MCP。该计划不提前批准任何 Slice 的实现。

## 开始实现前 Gate

- 完成现有练习、memory 和 eval prototype 的事实盘点，明确可复用能力与禁止继承的本地状态。
- 人工接受 Stage 4 首个 Slice 的 Goal、用户路径、失败行为、完成标准和明确不做项。
- 人工接受 schema、版本、评分、掌握度、Memory、删除、队列、预算和敏感数据边界的 ADR。
- 为公开或脱敏样本定义自动化与人工 eval；不得提交真实用户答案、上传原文、敏感 prompt 或 provider 配置。
- Spec/ADR Gate 通过前，不实现 Stage 4 业务 schema、练习 Agent、评分、掌握度、复习队列或长期 Memory。

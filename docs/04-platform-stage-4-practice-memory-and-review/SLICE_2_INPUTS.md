# Stage 4 Slice 2 输入：掌握度、复习队列与可管理 Memory

状态：分析输入已归档；对应 Spec/ADR 已于 2026-07-17 通过人工 Gate

日期：2026-07-17

## 目标

把 Slice 1 的多次学习与作答事实转化为用户能理解、纠正、删除和重新计算的薄弱点与复习建议，并只在明确规则下提升为长期 Memory。

Slice 2 不是“把分数存进 Memory”，而是建立以下可解释链路：

```text
Attempt / Feedback / Review completion
  -> Learning Event
  -> Mastery Signal
  -> Weakness
  -> Review Item
  -> 再次作答与重算
  -> confirmed Weakness 自动建立可管理 Memory
```

## 已有权威输入

- Practice Attempt 是不可变作答事实，绑定 Workspace、Item、Lesson Version 和递增 ordinal。
- 单选 Feedback 是确定性结果；简答 Feedback 是带 AI 标记、rubric 分项和引用的模型评估。
- Practice Set 和历史 Feedback 在来源 degraded 后仍可读，但不能产生新作答或评分。
- Attempt、Set、Course、来源和 Workspace 都可能删除；派生事实必须可撤回或清理。
- Tutor Session/Turn 仍是短期上下文，不自动成为 Learning Event 或长期 Memory。
- Postgres 是候选权威；Redis 只投递任务，Qdrant 只持有可重建索引。

## Slice 2 必须先决策的问题

1. 哪些行为构成 Learning Event：作答、查看反馈、重做、复习完成、跳过或 Tutor 对话是否分别入账？
2. 单选确定性结果、简答 AI score、rubric 分项和未答题应如何赋予不同信号权重？
3. 一次错误为何不能立即形成长期 Weakness；需要多少次、跨多少版本或多长时间的证据？
4. Mastery 是可见分数、分档状态还是内部信号；用户能否直接纠正，以及纠正如何保留审计来源？
5. Review Item 如何说明“为什么推荐”、关联哪道题/criterion/课节，并支持完成、跳过、稍后和再次验证？
6. 新证据、删除 Attempt、Feedback 修正、来源 degraded 或 Lesson 新版本发布后，哪些结果增量更新，哪些必须重算？
7. 哪些稳定事实有资格提升为长期 Memory；提升是否自动、需用户确认，如何衰减、过期、冲突和删除？
8. 用户关闭某类 Memory 后，既有数据如何处理，后续事件是否仍可用于临时复习但禁止长期提升？
9. 重算是同步事务、异步 Job 还是离线批处理；其幂等、取消、预算、trace 和失败事实如何定义？
10. Stage 4 最终删除 smoke 如何一次覆盖 Slice 1 与 Slice 2 的完整删除图？

## 建议文档拆分

- Spec 002：可解释掌握度、薄弱点和复习队列用户路径。
- ADR 003：Learning Event、Mastery Signal、Weakness、Review Item 的 Postgres 权威与重算。
- ADR 004：长期 Memory 的提升、来源、冲突、纠正、禁用、衰减、过期和删除。
- 前端概念：Reader/Practice/Tutor 旁的复习入口、推荐理由、Memory 管理和窄视口状态矩阵。
- Eval 设计：确定性事件矩阵、删除/重算、单次错误抗污染、解释完整性和人工教学质量 rubric。

## 明确不做

- 不把一次错误、一次满分或单次简答 AI score 直接写成稳定掌握度。
- 不把 Tutor history、LLM 自由摘要、prompt 隐藏状态、本地 JSON 或 Qdrant payload 当作长期 Memory 权威。
- 不提前实现 Slice 3 Skill、Slice 4 MCP、认证、多租户 membership 或自主多 Agent。
- Spec/ADR 和新页面概念未经人工 Gate，不生成 GLM 实现任务包。

## Gate 结论

- Mastery/Weakness/Review/Memory 的含义、用户可见性、抗单次污染、纠正、删除、重算和来源解释规则已获人工接受。
- confirmed Weakness 自动、确定性建立 Memory；用户管理内容与生命周期，Tutor 外发由 Workspace 开关单独控制。
- schema、任务、预算、删除图、eval 和前端概念已获人工接受，可以进入实现交接。

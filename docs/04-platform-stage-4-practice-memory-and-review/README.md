# Platform Stage 4：练习、记忆与复习闭环

状态：Slice 1、Slice 2 已完成并于 2026-07-18 通过人工主路径验收；下一步进入 Slice 3 教学 Skill 的事实盘点与 Spec/ADR 分析

Stage 4 的目标是让用户在课程学习之后完成练习和作答，获得有引用依据的反馈，并将可解释的薄弱点形成可管理的复习队列。任何 schema、生成 Agent、评分、掌握度或长期 Memory 实现，都必须先经过本阶段 Spec/ADR 和人工 Gate。

当前入口：

- [Stage 4 输入](STAGE_4_INPUTS.md)
- [Stage 4 四切片方向计划](STAGE_4_SLICE_PLAN.md)
- [Slice 1 练习与评分事实盘点](SLICE_1_PRACTICE_FACT_INVENTORY.md)
- [Slice 1 前端概念与状态矩阵](SLICE_1_FRONTEND_CONCEPT.md)
- [Slice 1 Spec：课节练习、作答与可信反馈](specs/001-lesson-practice-attempts-and-trustworthy-feedback.md)
- [ADR 001：练习快照、作答与删除权威](adr/001-practice-snapshots-attempts-and-deletion-authority.md)
- [ADR 002：受控练习生成、评分、队列与 trace](adr/002-controlled-practice-generation-grading-queue-and-trace.md)
- [Slice 1 GLM 实现任务包](SLICE_1_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 1 GLM 修正任务包 001](SLICE_1_GLM_CORRECTION_PACKET_001.md)
- [Slice 1 GLM 修正任务包 002](SLICE_1_GLM_CORRECTION_PACKET_002.md)
- [Slice 1 GLM 修正任务包 003](SLICE_1_GLM_CORRECTION_PACKET_003.md)
- [Slice 1 完成总结](SLICE_1_SUMMARY.md)
- [Slice 2 输入](SLICE_2_INPUTS.md)
- [Slice 2 Memory 事实盘点](SLICE_2_MEMORY_FACT_INVENTORY.md)
- [Slice 2 前端概念](SLICE_2_FRONTEND_CONCEPT.md)
- [Spec 002：可解释掌握度、复习队列与可管理学习 Memory](specs/002-explainable-mastery-review-and-managed-memory.md)
- [ADR 003：Learning Event、掌握度与复习投影权威](adr/003-learning-events-mastery-and-review-projections.md)
- [ADR 004：用户管理的长期学习 Memory](adr/004-user-managed-learning-memory.md)
- [Slice 2 GLM 实现任务包](SLICE_2_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 2 GLM 修正任务包 001](SLICE_2_GLM_CORRECTION_PACKET_001.md)
- [Slice 2 完成总结](SLICE_2_SUMMARY.md)
- [Slice 3 输入](SLICE_3_INPUTS.md)
- [Slice 1 OCR 记录](reviews/2026-07-16-slice-1-ocr.md)
- [Slice 2 OCR 记录](reviews/2026-07-17-slice-2-ocr.md)
- [Stage 3 总结](../03-platform-stage-3-chapter-learning-and-tutor/STAGE_3_SUMMARY.md)

Slice 2 已建立可解释掌握度、复习队列、可管理学习 Memory 与课节完成事实。Slice 3 可以读取这些已授权事实来选择和执行教学方法，但不得把 Skill 变成新的隐藏事实来源，也不得提前引入 Slice 4 MCP。

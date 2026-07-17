# Platform Stage 4：练习、记忆与复习闭环

状态：Slice 1 已于 2026-07-17 完成实现、独立复核、OCR、自动化门禁与人工 Chrome 主路径验收；当前进入 Slice 2 掌握度、复习队列与 Memory 的 Spec/ADR 分析

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
- [Slice 1 OCR 记录](reviews/2026-07-16-slice-1-ocr.md)
- [Stage 3 总结](../03-platform-stage-3-chapter-learning-and-tutor/STAGE_3_SUMMARY.md)

Slice 1 的练习、作答和反馈事实可作为 Slice 2 输入，但不得被直接解释为掌握度或长期 Memory。Slice 2 仍须先完成人工可见的推断、纠正、删除、重算和复习队列合同，再生成 GLM 实现任务包。

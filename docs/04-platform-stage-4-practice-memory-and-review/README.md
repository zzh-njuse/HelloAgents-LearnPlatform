# Platform Stage 4：练习、记忆与复习闭环

状态：Slice 1/2/3/4 已完成；新增计划外 Slice 5 负责练习生成与评分链路稳定化，等待 Spec/ADR Gate

Stage 4 的目标是让用户在课程学习之后完成练习和作答，获得有引用依据的反馈，并将可解释的薄弱点形成可管理的复习队列。任何 schema、生成 Agent、评分、掌握度或长期 Memory 实现，都必须先经过本阶段 Spec/ADR 和人工 Gate。

当前入口：

- [Stage 4 输入](STAGE_4_INPUTS.md)
- [Stage 4 五切片方向计划](STAGE_4_SLICE_PLAN.md)
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
- [Slice 3 教学 Skill 与 Tutor 事实盘点](SLICE_3_SKILL_FACT_INVENTORY.md)
- [Slice 3 教学 Skill 运作示例](SLICE_3_SKILL_EXAMPLE.md)
- [Slice 3 Tutor 教学方式前端概念](SLICE_3_FRONTEND_CONCEPT.md)
- [Spec 003：证据引导的诊断式支架教学 Skill](specs/003-evidence-guided-diagnostic-scaffold-skill.md)（已接受）
- [ADR 005：产品拥有的版本化教学 Skill 与 Tutor 执行边界](adr/005-product-owned-versioned-teaching-skill-runtime.md)（已接受）
- [Slice 3 GLM 实现任务包](SLICE_3_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 3 完成总结](SLICE_3_SUMMARY.md)
- [Slice 3 OCR 记录](reviews/2026-07-19-slice-3-ocr.md)
- [Slice 4 输入](SLICE_4_INPUTS.md)
- [Slice 4 MCP 事实盘点](SLICE_4_MCP_FACT_INVENTORY.md)
- [Slice 4 公式、代码练习与科学工具前端概念](SLICE_4_FRONTEND_CONCEPT.md)（修订版已接受）
- [Spec 004：科学内容渲染与受控 MCP 教学闭环](specs/004-controlled-python-execution-mcp-lab.md)（修订版已接受）
- [ADR 006：审核制 MCP 教学编排、执行与科学验证边界](adr/006-product-owned-mcp-python-execution-boundary.md)（修订版已接受）
- [Slice 4 增量 GLM 5.1 实现任务包 002](SLICE_4_GLM_IMPLEMENTATION_PACKET_002.md)
- [Slice 4 GLM 5.1 实现任务包](SLICE_4_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 4 完成总结](SLICE_4_SUMMARY.md)
- [Slice 4 OCR 记录](reviews/2026-07-23-slice-4-ocr.md)
- [Slice 5 输入：练习生成与评分链路稳定化](SLICE_5_INPUTS.md)
- [Slice 1 OCR 记录](reviews/2026-07-16-slice-1-ocr.md)
- [Slice 2 OCR 记录](reviews/2026-07-17-slice-2-ocr.md)
- [Stage 3 总结](../03-platform-stage-3-chapter-learning-and-tutor/STAGE_3_SUMMARY.md)

Slice 4 已建立两项经过管理员审核的 capability，并完成真实 Judge0/Wolfram 接入、课程科学验证、编程/科学练习、Tutor 自主讲解与本地公式渲染。人工 smoke 同时证明练习生成和评分链路仍需独立稳定化，因此 Stage 4 增加 Slice 5，但不得借机扩展 MCP 范围或硬编码测试输入。

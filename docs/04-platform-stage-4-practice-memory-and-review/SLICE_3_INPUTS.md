# Stage 4 Slice 3 输入：教学 Skill 与 Tutor 质量

状态：待事实盘点、Spec/ADR 与人工 Gate

日期：2026-07-18

## 目标

选择一种有明确学习价值的教学方法，将其从散落 prompt 提升为可版本化、可选择、可观测、可评估的产品 Skill，并用它缩小 Tutor 回答质量的上下限差距。

## 已有权威输入

- RAG 提供固定 Course/Lesson Version 下可引用的课程依据。
- Practice 提供不可变题目、Attempt、客观评分与受控主观反馈。
- Slice 2 提供可重算 mastery band、Weakness、Review Item、active Learning Memory 与 Lesson Completion。
- Tutor 已具备 Session/Turn、范围隔离、引用、任务状态、预算、失败、重试、取消和最小 trace。
- Memory 与 Lesson Completion 只有在 Workspace 明确开启时才可发送给外部 Tutor provider；当前范围与实际使用数量可见。

## 必须解决的问题

1. 首个教学 Skill 具体采用哪种方法，以及为什么它比继续调整通用 Tutor prompt 更有独立价值。
2. Skill 的名称、版本、适用条件、输入、输出、预算、失败行为、用户可见性和历史追溯合同。
3. Tutor 如何根据用户问题综合课程依据、薄弱点、掌握度和课节完成记录，而不是简单复述 Memory 列表。
4. 宽泛问题、具体概念问题、诊断问题和学习规划问题分别应产生怎样的结构化教学响应。
5. 如何禁止根据某个人工 smoke 问句、关键词或预期答案增加硬编码捷径，并用同类变体和反例验证通用行为。
6. Skill 未命中、输入不足、资料冲突、引用不足、provider 失败和预算耗尽时如何诚实降级。
7. 如何通过固定离线 eval 与真实教学质量 rubric 证明 Skill 相比普通 Tutor 基线有可重复收益。

## Tutor 优化验收方向

- 回答应针对用户意图进行综合、解释和排序，不把 Memory 或 Lesson Completion 原样拼接成答案。
- “接下来学什么”一类宽泛问题应给出有依据的优先顺序、原因和可执行学习动作，同时明确不确定性。
- “我的薄弱点是什么”应区分确定薄弱点、初步建议、掌握度证据不足和已完成课节，不混淆这些事实。
- 具体知识问题仍以课程资料和引用为主要依据；Memory 只用于调整解释重点，不替代事实依据。
- 对不同措辞的等价问题保持一致策略；对不应触发个性化的反例不得强行套用 Memory。

## 非目标

- 不一次加入多种教学 Skill，不为展示 framework 而制造 Skill 数量。
- 不把 Skill 文件、prompt 或模型自由摘要当成新的学习事实来源。
- 不改变 Slice 2 掌握度公式，不让 Tutor 自由改写 Weakness 或 Memory 权威事实。
- 不引入 MCP、代码执行沙箱、数学工具、日历、自主多 Agent、认证或多租户。
- 不把固定问句映射到固定输出，也不以测试专用捷径冒充教学能力。

## 开始门禁

- 先完成现有 Tutor prompt、agent、eval 与失败样例的事实盘点。
- 提供 Skill 信息架构、Tutor 交互概念和基线/候选对比 eval 方案。
- Spec/ADR 经人工逐项接受后，才生成 GLM 实现任务包或开始业务实现。

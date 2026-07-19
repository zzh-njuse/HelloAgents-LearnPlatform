# Platform Stage 4 四切片方向计划

状态：方向计划，已于 2026-07-16 完成范围对齐；不替代各 Slice 的 Spec/ADR 与人工 Gate

## 总体目标

Stage 4 在 Stage 3 的课程阅读、引用和 Tutor 基础上形成可解释的学习反馈闭环：

```text
课节学习 -> 练习 -> 作答 -> 反馈 -> 薄弱点/掌握度 -> 复习 -> 再验证
```

四个 Slice 按事实依赖顺序推进。前一 Slice 只提供后一 Slice 可依赖的产品事实，不以一次性 prompt、隐藏状态或外部工具结果替代 Postgres 权威合同。

## Slice 1：练习、作答与反馈（已完成）

目标：在 Course Reader 内完成最小可用的练习闭环。

候选范围：

- 基于固定 Course Version / Lesson Version 和来源快照生成少量练习。
- 定义 Exercise、Exercise Version、Rubric、Attempt、Answer 和 Feedback。
- 覆盖客观题与一种受控主观题；题目和反馈声明资料依据时必须带可回读引用。
- 用户可以提交作答、查看反馈、重新作答并查看历史结果。
- 生成和评分具备幂等、任务状态、失败收敛、取消、预算和最小 trace。
- Workspace、Course、Lesson 或来源删除时有明确清理或保留依据。

完成 Gate：已于 2026-07-17 完成。练习版本、作答和反馈可追溯；评分失败不提交伪成功；固定离线 eval、OCR 与 Chrome 主路径 smoke 已通过。删除类人工 smoke 经人工确认统一延后到 Stage 4 最终 Gate，自动化删除门禁继续保留。

明确不做：掌握度长期推断、复习队列、长期 Memory、Skill 产品化和 MCP。

## Slice 2：掌握度、复习队列与可管理 Memory（已完成）

目标：把多次学习与作答事件转化为可解释、可纠正的复习建议。

候选范围：

- 定义 Learning Event、Mastery Signal、Weakness 和 Review Item 的权威事实与版本关系。
- 基于多次事件更新掌握度，避免一次错误永久污染用户画像。
- 提供 Review Queue、推荐理由、完成/跳过/稍后复习和再次验证。
- 明确哪些学习事件可提升为长期 Memory，以及提升、来源、冲突、衰减、过期和重算规则。
- 用户可以查看、纠正、删除 Memory，或禁止某类事件进入长期状态。
- 将练习、掌握度、复习和 Memory 纳入 Workspace 删除权威与 eval。

完成 Gate：已于 2026-07-18 完成。用户能够理解复习依据、管理 Memory、记录课节完成状态，并在 Tutor 中按当前范围受控使用这些事实；自动化、OCR 与 Chrome 主路径 smoke 已通过。破坏性删除 smoke 继续按既定决策延后至 Stage 4 最终 Gate。

明确不做：把 Tutor Session history 直接升级为 Memory；以隐藏 prompt、本地 JSON 或模型自由摘要作为产品事实；Skill/MCP。

## Slice 3：教学 Skill 产品化（已完成）

目标：把一种已证明有学习价值的教学方法从散落 prompt 提升为可版本化、可选择、可评估的 Skill。

候选方向在 Slice 3 Spec 前确定，优先考虑：

- 苏格拉底式分层提示；
- 错因诊断与针对性反馈；
- 检索练习或渐进式练习；
- worked example 与逐步撤除支架；
- 基于薄弱点的复习策略。

Skill 合同至少定义名称、版本、适用条件、输入、输出、预算、失败行为、用户可见性以及效果 eval。Skill 只能读取已授权的课程、练习和 Memory 事实，不拥有新的隐藏事实来源。

完成 Gate：已于 2026-07-19 完成。诊断式教学 Skill v2 已成为默认教学方法，v1 历史可追溯；Tutor 能综合课程依据与授权学习状态并保持引用、范围、预算、失败和删除边界。自动化、OCR 与 Chrome 主路径 smoke 已通过。

明确不做：为了展示 framework 而一次加入多种 Skill；用 Skill 文件替代 Exercise、Attempt、Mastery 或 Memory schema；自主多 Agent。

## Slice 4：MCP 外部工具闭环（事实盘点与 Spec/ADR 准备）

目标：只在存在明确且不能由内部能力合理替代的学习场景时，引入一个受控 MCP 工具闭环。

当前候选但尚未决定：

- 代码执行沙箱；
- 数学计算或符号工具；
- 外部日历与复习计划同步。

Slice 4 Spec 前必须先选定一个具体场景并回答：

- 为什么必须使用外部工具，内部 adapter 为什么不足；
- 谁授权、哪些数据可以外发、用户如何确认或撤销；
- 工具输入如何最小化，是否包含用户答案或课程资料；
- 返回结果如何标注工具来源、版本和可信边界；
- 超时、不可用、部分成功、重试、幂等、预算和取消如何收敛；
- MCP server 是默认 self-host、可选部署还是第三方服务；
- 工具调用如何进入安全 trace、删除权威和 eval。

完成 Gate：一个具体外部工具场景端到端可用，失败时不破坏练习/复习权威事实，且外发、授权和删除行为通过人工安全验收。

明确不做：把内部 Postgres/Qdrant/Redis 操作包装成 MCP；同时接入多个未验证工具；默认开放网页搜索、任意命令执行或无边界外发。

## 跨切片规则

- 每个 Slice 单独完成事实盘点、Spec、必要 ADR、独立 review、人工 Gate、实现、OCR/复验和阶段记录。
- 非平凡编码在 Gate 后按 [GLM 实现交接工作流](../GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md)生成任务包并交给 GLM；Codex 不以需求处理者身份静默接管主体实现。
- Slice 方向可以在对应 Spec 前调整；后续 Slice 不得反向迫使前序 schema 提前过度设计。
- RAG 继续负责“资料中有什么”，Memory 负责“用户学过什么和哪里薄弱”，Skill 负责“如何教与练”，MCP 负责“哪些外部工具能力确有必要”。
- Exercise Agent、Review Coach 或多 Agent 只在职责、artifact、重试/取消和成本边界真正可分时另行决策，不是四切片默认前提。
- Stage 4 不顺带实现认证、多租户 SaaS、金额计费、通用网页搜索或完整运维平台。

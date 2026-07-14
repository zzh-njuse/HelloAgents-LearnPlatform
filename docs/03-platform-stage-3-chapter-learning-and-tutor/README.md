# Platform Stage 3：章节化学习与 Tutor

状态：Slice 1 已于 2026-07-14 完成实现、独立 OCR、复验和人工浏览器验收。下一步仅准备 Slice 2 的 Tutor Spec/ADR；session 与 memory 的具体边界仍需先经人工 Gate。

## 目标

在已完成的资料生命周期与引用检索之上，建立首条可重复学习路径：用户将 ready 资料组织成可版本化章节，在 Course Reader 中阅读，并在当前章节上下文内获得带引用、可拒答的辅导。

## 已确认输入

1. [Stage 2 总结与 Stage 3 输入](../02-platform-stage-2-material-lifecycle-and-citation-retrieval/STAGE_2_SUMMARY_AND_STAGE_3_INPUTS.md)
2. [学习平台蓝图](../LEARNING_AGENT_BLUEPRINT.md)
3. [Self-host 开发路线](../SELF_HOST_DEVELOPMENT_ROADMAP.md)
4. [数据库与部署计划](../DATABASE_AND_DEPLOYMENT_PLAN.md)
5. [Agent 协作开发流程](../AGENT_COLLABORATION_PLAYBOOK.md)
6. [Slice 1 总结与 Slice 2 输入](SLICE_1_SUMMARY_AND_SLICE_2_INPUTS.md)

## 进入实现前的 Gate

- 先完成正确仓库、Stage 2 合同和 `academic_companion` 可复用资产的事实盘点。
- Spec 明确用户路径、Course Reader、章节发布/重生成、Tutor 失败模式与验收。
- ADR 明确课程事实/版本/删除、Tutor runtime/session/memory/tool 权限、生成任务/trace/eval 边界。
- Spec/ADR 经人工接受后，再提出小范围实现计划；不以现有单轮带引用回答反向推定 Tutor 合同。

## Agent 能力候选大纲

本节仅保存后续分析的地图，不是已确认的切片、schema 或技术选型。Stage 3 事实盘点后，可以从以下候选顺序起草 Spec：

1. **课程事实与受控生成**：先定义 course/section/lesson/version/citation、发布与重生成，再评估 Course Architect 和 Lesson Writer 是否需要独立 Agent。
2. **Tutor Agent 核心**：把 Stage 2 RAG/citation 作为受权限证据工具，定义当前课程/章节上下文、停止条件、工具白名单、预算、取消、拒答和最小 run/tool trace。
3. **可选的 Agent 能力扩展**：只在已证明产品价值后，再评估 Skill、一个有界 MCP 场景或 Course Architect -> Lesson Writer 的结构化多 Agent 交接。这些能力可以留到后续 Stage，不为了展示而挤入 Stage 3。

### 各能力必答问题

| 能力 | Stage 3 必须回答 |
|---|---|
| RAG | Agent 何时检索、如何限定 workspace/course/section、何时拒答、如何评测引用正确性？ |
| Memory/context | 哪些只是当前请求或 session 上下文，哪些未来才有资格提升为可管理的长期 memory？ |
| Skill | 它解决什么可重复的教学方法，如何版本化、选择、显示和 eval？ |
| MCP | 为什么需要外部工具，谁授权，哪些数据可以外发，结果如何带来源且失败时如何收敛？ |
| 多 Agent | 职责是否真正可分，交接 artifact 是什么，谁拥有编排、重试、取消和部分成功语义？ |

候选能力无论是直接复用 `hello_agents`，还是包装 `academic_companion`，都必须遵守 `apps -> academic_companion -> hello_agents` 依赖方向，由 product app 拥有 workspace、权限、状态、trace 和对外 API。

## 明确不提前做

- 练习、掌握度、长期复习队列与 Stage 4 memory 模型。
- 自主网页搜索、MCP 工具循环、无约束 Agent 或把 prototype session 直接作为产品状态。
- 绕过 Postgres 事实和 Stage 2 citation 回读的课程/回答实现。

## 后续文档位置

- [Slice 1 Spec：版本化课程与受控课程生成](specs/001-versioned-course-and-controlled-generation.md)
- [ADR 001：课程事实、版本、发布与来源生命周期](adr/001-course-authority-versioning-publication-and-source-lifecycle.md)
- [ADR 002：受控课程 Agent、工具、任务与最小审计轨迹](adr/002-controlled-course-agents-tools-jobs-and-trace.md)
- [specs/](specs/README.md)：Stage 3 功能规格索引。
- [adr/](adr/README.md)：Stage 3 跨模块决策索引。
- [reviews/](reviews/README.md)：记录 Stage 3 的独立审查与人工验收。
- [Slice 1 总结与 Slice 2 输入](SLICE_1_SUMMARY_AND_SLICE_2_INPUTS.md)：记录已交付合同、验证事实、暂缓风险和 Tutor 规格输入。

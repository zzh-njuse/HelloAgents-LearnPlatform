# Platform Stage 3：章节化学习与 Tutor

状态：文档准备中。尚未起草或接受 Stage 3 Spec/ADR，禁止开始 course、lesson、Tutor、Agent runtime、session、memory 或对应 migration 的业务实现。

## 目标

在已完成的资料生命周期与引用检索之上，建立首条可重复学习路径：用户将 ready 资料组织成可版本化章节，在 Course Reader 中阅读，并在当前章节上下文内获得带引用、可拒答的辅导。

## 已确认输入

1. [Stage 2 总结与 Stage 3 输入](../02-platform-stage-2-material-lifecycle-and-citation-retrieval/STAGE_2_SUMMARY_AND_STAGE_3_INPUTS.md)
2. [学习平台蓝图](../LEARNING_AGENT_BLUEPRINT.md)
3. [Self-host 开发路线](../SELF_HOST_DEVELOPMENT_ROADMAP.md)
4. [数据库与部署计划](../DATABASE_AND_DEPLOYMENT_PLAN.md)
5. [Agent 协作开发流程](../AGENT_COLLABORATION_PLAYBOOK.md)

## 进入实现前的 Gate

- 先完成正确仓库、Stage 2 合同和 `academic_companion` 可复用资产的事实盘点。
- Spec 明确用户路径、Course Reader、章节发布/重生成、Tutor 失败模式与验收。
- ADR 明确课程事实/版本/删除、Tutor runtime/session/memory/tool 权限、生成任务/trace/eval 边界。
- Spec/ADR 经人工接受后，再提出小范围实现计划；不以现有单轮带引用回答反向推定 Tutor 合同。

## 明确不提前做

- 练习、掌握度、长期复习队列与 Stage 4 memory 模型。
- 自主网页搜索、MCP 工具循环、无约束 Agent 或把 prototype session 直接作为产品状态。
- 绕过 Postgres 事实和 Stage 2 citation 回读的课程/回答实现。

## 后续文档位置

- [specs/](specs/README.md)：经人工确认后创建 Stage 3 功能规格。
- [adr/](adr/README.md)：经人工确认后创建跨模块或不可逆决策。
- [reviews/](reviews/README.md)：记录 Stage 3 的独立审查与人工验收。

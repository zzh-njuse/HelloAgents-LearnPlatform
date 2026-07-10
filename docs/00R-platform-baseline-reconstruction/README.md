# Platform Stage 0R：正确仓库基线重建

状态：进行中，仅文档与验证

日期：2026-07-10

## 目标

以正确仓库的真实代码为事实基础，以已经按当前代码修缮的高层指导文档为产品目标，重新建立进入 self-host 学习平台开发前的工程基线。

Stage 0R 不迁移误仓库业务代码，也不开始 Stage 1 平台实现。

## 当前文档

- Spec：`specs/001-correct-repository-baseline-reconstruction.md`
- ADR：`adr/001-product-layer-and-dependency-boundaries.md`
- 现状评估与重新计划：`CURRENT_STATE_AND_REPLAN.md`
- Review 记录模板：`reviews/README.md`
- 产品蓝图：`../LEARNING_AGENT_BLUEPRINT.md`
- 开发路线：`../SELF_HOST_DEVELOPMENT_ROADMAP.md`
- 数据库与部署：`../DATABASE_AND_DEPLOYMENT_PLAN.md`
- 协作流程：`../AGENT_COLLABORATION_PLAYBOOK.md`
- 仓库级规则：`../../AGENTS.md`
- 历史总结：`../history/LEGACY_AND_RECOVERY_SUMMARY.md`

## 已确认方向

- 产品是资料驱动的学习平台，不是 chat-first 双模式应用。
- `hello_agents` 和 `academic_companion` 是可复用资产，product app 负责产品状态和入口。
- Postgres 是事实来源；Qdrant 可重建；Redis 非权威。
- `academic_companion` 中的 API/Web 是待吸收原型。
- 八股/LeetCode 只作为测试和演示材料，不主导产品设计。
- 误仓库 Stage 1 代码只作参考，先完成文档和验证。

## Stage 0R 完成标志

- 产品三层边界有已接受 ADR。
- 当前 API/Web/Agent prototype contract 有清单。
- Python、Web 和必要服务的依赖与验证命令可复现。
- Stage 1 的输入、非目标和待决项明确。
- 工作区干净，所有 Stage 0R 产物可追溯。

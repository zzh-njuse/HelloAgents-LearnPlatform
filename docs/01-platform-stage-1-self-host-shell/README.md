# Platform Stage 1：Self-Host 平台壳

状态：实现、OCR 评审、人工 Web 核验与本地验收完成；等待提交
日期：2026-07-10

Stage 1 建立最小可 self-host 的学习平台壳，证明产品边界、数据拓扑、Web workbench 与 workspace 身份，而不提前实现 ingestion、agent chat、课程或练习。

建议按以下顺序评审：

1. [规格说明](specs/001-self-host-platform-shell.md)
2. [应用技术栈 ADR](adr/001-stage-1-application-stack-and-prototype-bridge.md)
3. [参考实现采用矩阵](MIGRATION_ADOPTION_MATRIX.md)
4. [Self-Host 运行手册](SELF_HOST_RUNBOOK.md)
5. [Review 记录](reviews/README.md)
6. [Stage 1 总结与 Stage 2 输入](STAGE_1_SUMMARY_AND_STAGE_2_INPUTS.md)

本 Stage 与误仓库 Legacy Phase 1 代码刻意分离：后者是参考集，不是待应用的补丁。

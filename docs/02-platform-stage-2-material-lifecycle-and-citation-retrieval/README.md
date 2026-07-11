# Platform Stage 2：资料生命周期与引用检索

状态：已建立文档入口；尚未开始实现

Stage 2 将把 Stage 1 的 workspace 壳扩展为资料上传、异步入库、检索和可定位引用的学习平台能力。它仍然不是 chat-first 应用，也不为八股或 LeetCode fixture 建立专用数据模型。

## 已确认的参考输入

1. [Stage 1 总结与 Stage 2 输入](../01-platform-stage-1-self-host-shell/STAGE_1_SUMMARY_AND_STAGE_2_INPUTS.md)
2. [学习平台蓝图](../LEARNING_AGENT_BLUEPRINT.md)
3. [Self-host 开发路线图](../SELF_HOST_DEVELOPMENT_ROADMAP.md)
4. [数据库与部署计划](../DATABASE_AND_DEPLOYMENT_PLAN.md)
5. [Agent 协作开发流程](../AGENT_COLLABORATION_PLAYBOOK.md)
6. [产品分层与依赖边界 ADR](../00R-platform-baseline-reconstruction/adr/001-product-layer-and-dependency-boundaries.md)
7. [原型合约盘点](../00R-platform-baseline-reconstruction/PROTOTYPE_CONTRACT_INVENTORY.md)

这些输入已足以开始 Stage 2 的规格与 ADR 工作；它们不替代 Stage 2 自身的产品合同。

## 已确认范围

### Slice 1：单文件资料管线

- 在既有 workspace 中接收单个 PDF、Markdown 或 TXT 文件。
- 记录 document、version、parse report、chunk 与 ingestion job 的权威元数据和状态。
- 使用 local storage 保存原始字节；Postgres 为事实来源；Qdrant 只保存可重建索引；Redis 只协调非权威任务。
- 完成异步解析、切块、embedding、索引、检索结果与可定位引用。
- 只返回检索结果和引用证据，不在本切片调用 LLM 生成答案。

### Slice 2：批量与带引用回答

- 批量上传中每个文件拥有独立的 document/version/job、失败与重试语义。
- 在 Slice 1 的稳定检索链路上增加带引用的 LLM 回答与资料问答界面。

## 进入实现前的 Gate

- `specs/` 中的 Slice 1 Spec 经人工确认。
- `adr/` 中明确资料所有权、版本、删除、索引重建、job 幂等与重试语义。
- 明确首个 parser、embedding provider、Qdrant collection 命名与 worker 运行边界。
- Slice 2 不得在 Slice 1 的检索和引用合同稳定前实现。

## 明确暂不做

- 万能 parser、图片 OCR、Office、网页或 Git 批量导入。
- 完整自然语言课程或练习闭环。
- 多用户鉴权、Neo4j，或为既有八股/LeetCode fixture 设计专用模型。

OCR、Office 和网页导入是未来 parser extension 的候选项，不是永久排除项。

## 文档入口

- [规格目录说明](specs/README.md)
- [ADR 目录说明](adr/README.md)
- [评审记录目录说明](reviews/README.md)

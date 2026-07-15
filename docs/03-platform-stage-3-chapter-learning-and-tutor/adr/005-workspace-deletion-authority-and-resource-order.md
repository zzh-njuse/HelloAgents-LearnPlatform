# ADR 005：Workspace 删除事实与资源清理顺序

状态：已接受（2026-07-15 人工 Gate）

日期：2026-07-15

## 1. 决策摘要

建议以 Postgres Workspace `deleting` 状态作为删除权威起点，以独立 WorkspaceDeletionJob 管理重试。清理顺序为“取消工作 -> Qdrant -> storage -> Postgres 子记录 -> Workspace”，最终硬删除 Workspace。Redis 消息和 Qdrant 都不是删除事实来源。

## 2. 背景

当前 Workspace 没有 lifecycle 或删除 API，且所有业务表直接或间接引用 Workspace。现有外键没有形成完整 cascade 图，直接 `DELETE workspaces` 会失败，也无法处理 storage、Qdrant 和运行中的 worker。

## 3. 决策

- Workspace 新增 `lifecycle_status` 和 `deleted_at`；普通查询只返回 active。
- DeletionJob 独立保存 `workspace_id` 字符串、状态、attempt、lease、错误码和时间，不使用 Workspace FK。
- 创建 job 和标记 deleting 在同一事务完成。
- 所有业务入口在 Workspace 非 active 时拒绝新操作。
- worker 在 claim、provider/tool 前后和最终提交前检查 Workspace 状态。
- 外部资源按 workspace ID 幂等删除后，Postgres 使用显式拓扑顺序硬删除。
- Workspace 删除完成后，DeletionJob 保留最小状态，供 UI 确认结果；不保存名称或资源正文。

## 4. 为什么不直接级联

只给 `workspace_id` 外键增加 cascade 仍不足够：DocumentVersion、Chunk、ParseReport、Lesson 等通过中间父表间接引用 Workspace，且 SourceDocument/Course/Lesson 有 current pointer 环。一次性修改全部外键的风险和 migration 范围大于显式清理服务。

当前选择显式拓扑删除并以集成测试锁定顺序。未来若统一重构 FK cascade，需要单独 migration ADR。

## 5. 一致性与失败恢复

- 标记 deleting 后，即使 queue 投递失败，reconciler 也能从 Postgres 找回任务。
- Qdrant 或 storage 删除成功、DB 失败：重试再次删除外部资源并继续 DB，操作幂等。
- DB 已删除业务正文但最终 Workspace 删除失败：Workspace 仍 deleting，重试完成最后步骤。
- 迟到 worker 看到 deleting/missing 后丢弃结果，不得恢复资源。
- 备份不在在线删除事务内；文档明确由 self-host 管理者单独处理。

## 6. 未采用方案

- **只在前端隐藏**：拒绝，数据和成本仍存在。
- **同步 HTTP 全量删除**：拒绝，容易超时且无法可靠重试外部资源。
- **先删除 Postgres 再清理外部资源**：拒绝，会丢失可恢复的清理事实。
- **自动识别并批量删除测试 Workspace**：拒绝，误删风险不可接受。
- **永久软删除所有 Workspace 内容**：拒绝，不能满足清理测试数据和资料字节的目标。

## 7. 生效条件

人工需确认：最终硬删除、名称确认、异步任务、外部资源顺序、DeletionJob 最小保留，以及备份不在应用删除保证内。未经确认不修改 schema 或实现删除 API。

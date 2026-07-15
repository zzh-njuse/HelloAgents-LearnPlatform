# Spec 003：Workspace 安全删除

状态：已接受（2026-07-15 人工 Gate）

日期：2026-07-15

适用阶段：Platform Stage 3 Slice 2 前置维护切片

## 1. 评审结论摘要

本规格建议为测试和真实 Workspace 增加显式删除能力。删除不是只移除列表项：它必须先把 Workspace 标记为 deleting、阻止新操作并取消任务，再异步删除 Qdrant points、storage 文件以及 Postgres 中的资料、课程、trace 和未来 Tutor 数据，最后硬删除 Workspace。

Web 在 Workspace 操作区提供垃圾桶图标和影响摘要，要求用户在确认框中确认 Workspace 名称。删除不可撤销；备份副本不在应用删除能力范围内。

## 2. Goal 与成功标准

- 用户可以清理大量测试 Workspace，不再让列表持续堆积。
- 删除请求返回后 Workspace 立即从普通列表隐藏，且所有业务 API 拒绝继续写入。
- active ingestion/course/Tutor job 被请求取消；迟到结果不能重新写入。
- storage、Qdrant 和 Postgres 清理可重试，部分失败不会把 Workspace 恢复为 active。
- 完成后 Workspace 及其业务正文从主 Postgres、storage 和 Qdrant 中消失。

## 3. 范围与非目标

范围内：删除预览、确认、异步 job、取消现有任务、Qdrant/storage/Postgres 清理、Web 状态、focused tests 和人工 smoke。

不做：批量多选删除、自动删除“看起来像测试”的 Workspace、回收站恢复、备份擦除、多用户权限和保留策略管理。

## 4. 用户流程

1. 用户点击 Workspace 行或详情中的垃圾桶图标。
2. Web 请求删除影响摘要：资料数、课程数、运行任务数，以及未来 Tutor session 数。
3. 对话框说明会删除资料字节、索引、课程和对话，并要求输入 Workspace 名称确认。
4. `POST /api/v1/workspaces/{workspace_id}/deletion` 携带确认名称和 `Idempotency-Key`，返回 202 与 deletion job。
5. Workspace 立即进入 `deleting` 并从普通列表消失；Web 切换到其他 Workspace。
6. worker 执行清理；失败可通过 deletion job 重试。

## 5. 删除顺序

```text
Postgres: Workspace -> deleting，创建 deletion job
  -> 请求取消 ingestion/course/Tutor active work
  -> Qdrant 按 workspace_id 删除 points
  -> storage 删除 workspace_id 目录
  -> Postgres 按依赖顺序硬删除业务子记录
  -> 硬删除 Workspace
  -> deletion job succeeded
```

Qdrant/storage 删除必须幂等。外部资源先清理、Postgres 正文后清理；若数据库阶段失败，重试外部删除应安全返回成功。

## 6. API 草案

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/workspaces/{workspace_id}/deletion-impact` | 返回资料、课程、任务和 Tutor 数量 |
| `POST` | `/workspaces/{workspace_id}/deletion` | 校验名称和幂等键，创建删除任务 |
| `GET` | `/workspace-deletion-jobs/{job_id}` | Workspace 删除后仍可查询任务状态 |
| `POST` | `/workspace-deletion-jobs/{job_id}/retry` | 重试失败任务 |

Deletion job 的 `workspace_id` 是审计字符串而不是外键，否则 Workspace 无法最终硬删除。job 不保存 Workspace 名称、资料正文或内部路径。

## 7. 状态与失败

Workspace：`active -> deleting -> hard deleted`。

Deletion job：`queued -> running -> succeeded | retry_wait | failed`。

- Workspace 不存在：404。
- 确认名称不匹配：422。
- 已 deleting：返回既有 active deletion job，实现幂等。
- Qdrant/storage 暂时失败：retry_wait；Workspace 继续隐藏。
- DB 清理失败：failed/retry_wait，不恢复 active。

## 8. 数据与实现边界

- 新增 Workspace lifecycle/deleted timestamp 和独立 deletion job migration。
- 不依赖当前没有 `ON DELETE CASCADE` 的 FK 图直接删除 Workspace；服务必须用显式、经过测试的拓扑顺序清理。
- 清理范围包含 document/version/chunk/report、batch/item、ingestion job、RAG trace、course/version/section/lesson/citation/job、Agent run/tool call，以及实现时已经存在的 Tutor 表。
- Redis 中迟到消息可以残留，但 worker 必须因 Workspace deleting/missing 安全退出。

## 9. 验证

- 空 Workspace 和包含资料/课程的 Workspace 删除。
- active ingestion/course job 取消与迟到响应。
- Qdrant/storage 删除失败后重试。
- Workspace 隔离，不能删除或统计其他 Workspace 数据。
- 删除后 list/get/business API 行为。
- migration upgrade/downgrade、Web lint/build、Compose 和 Chrome 人工 smoke。
- 删除属于 OCR gate，真实 OCR 仍需单独人工确认。

## 10. 人工 Gate

1. 删除是最终硬删除，不提供回收站。
2. 必须输入 Workspace 名称确认，不提供自动或批量删除。
3. 删除采用异步、可重试流程；请求后立即隐藏 Workspace。
4. 删除覆盖 Postgres、storage 和 Qdrant，但不承诺擦除用户自行保存的备份。
5. Deletion job 在 Workspace 删除后保留不含正文的状态记录。

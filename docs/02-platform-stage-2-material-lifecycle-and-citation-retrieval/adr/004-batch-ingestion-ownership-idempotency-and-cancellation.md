# ADR 004：批量入库的所有权、幂等与取消

状态：已接受
接受日期：2026-07-13
日期：2026-07-12
适用阶段：Platform Stage 2 Slice 2

## 1. 决策摘要

新增 Postgres 权威的 `ingestion_batches` 与 `ingestion_batch_items`。batch 只表示一次用户操作及其汇总，每个有效 item 仍创建独立 document/version/ingestion job。批量允许部分成功；retry 和 cancel 按 item 执行，不回滚或删除已成功资料。

## 2. 背景

把多文件循环调用单文件 API 虽然实现简单，但无法稳定回答“哪些文件属于同一次操作、请求中断到哪里、retry-all 是否重复创建资料、取消影响哪些项”。反过来，把一个批次做成单一大 job 又会破坏 Slice 1 已验证的逐资料状态、重试和幂等边界。

## 3. 决策

### 3.1 权威身份

- batch 属于 workspace，保存用户一次提交的幂等键和汇总状态。
- item 通过 `(batch_id, client_ordinal)` 唯一，保存安全显示名、接收状态和可空的 document/version/job ID。
- document/version/job 继续拥有单份资料的生命周期；batch 不复制其处理事实。
- item 关联 job 后，其 processing/ready/failed 状态是对关联权威记录的缓存投影；retry、cancel 和最终判定必须回读 job/version，不能让两个状态机独立演进。
- batch 计数是可重算缓存。读取时若计数与 item/job 不一致，以 item 和关联权威状态为准并安排修复。

### 3.2 请求准入与部分提交

- 请求级先校验 workspace、文件数量、总声明/实际原始字节和 `Idempotency-Key`。
- 请求级准入失败时不创建 batch。
- 准入成功后先创建 batch/items，再按 ordinal 独立处理文件。
- 每个有效 item 使用自己的 storage/数据库提交边界；一个 item 失败不回滚其他已提交 item。
- API 在处理中崩溃时，reconciler 将长期 `accepting` 的 batch 收敛；没有 document/job 的 pending item 标记为 `upload_interrupted`，不假装可以从 Redis 恢复丢失的请求字节。

### 3.3 幂等

- Web 为每次明确提交生成 UUID `Idempotency-Key`。
- `(workspace_id, idempotency_key)` 唯一；重复请求返回原 batch。
- batch 保存有序文件名、声明大小与类型形成的请求元数据哈希；同一 key 但元数据哈希不同返回 409，避免误复用 key 静默返回无关批次。文件内容完整性仍以逐 item 实际 SHA-256 为准。
- item 关联 document 后不可再创建第二个 document。
- retry-all 只对当前可重试的关联 job 执行 Slice 1 的条件更新；queued/running/ready/rejected/canceled item 不重复 enqueue。

### 3.4 取消

- cancel 将 batch 置为 `cancel_requested`，并逐项请求取消 pending/accepted/queued item。
- 已 running item 在解析、embedding batch、Qdrant upsert 和最终提交边界检查取消；不能安全中断的当前原子步骤完成后再停止。
- ready/failed/rejected item 保持原结果。
- cancel 不是 delete。若用户希望删除已成功资料，必须使用 document 删除合同。
- batch 只有在所有未完成 item 收敛后进入 `canceled` 或含已成功项的终态摘要。

### 3.5 状态汇总

batch 终态按 item 推导：

| 条件 | batch 状态 |
|---|---|
| 仍在接收 | `accepting` |
| 至少一项未终止 | `processing` 或 `cancel_requested` |
| 全部 ready | `completed` |
| ready 与 failed/rejected/canceled 并存 | `partial_failed` |
| 无 ready 且存在 failed/rejected | `failed` |
| 无 ready 且所有可处理项 canceled | `canceled` |

## 4. 并发与事务边界

- 对 retry/cancel/汇总更新使用 batch 或 item 行锁与条件更新，不使用 Redis lock 作为正确性来源。
- 单项最终 ready 与 batch 摘要更新不要求同一跨服务事务；job/item 是权威，batch 摘要最终一致。
- 删除 document 后，item 仍保留历史关联，但读取时显示 `deleted`，不把它重新计为 ready 可用资料。

## 5. 影响

### 正向

- 用户能理解部分失败和请求中断。
- 保留 Slice 1 的逐资料重试、删除与幂等合同。
- 重复提交和 retry-all 不制造重复资料。

### 成本

- 增加两张表、汇总逻辑和 stale batch reconciliation。
- multipart 请求中断后无法恢复未持久化字节，用户需重新提交缺失项。
- cancel 是协作式而非任意指令级抢占。

## 6. 未采用方案

### Web 并发调用 N 次单文件 API

不采用为产品合同。缺少批次事实、统一幂等、整体进度和取消边界。

### 一个 batch 对应一个 ingestion job

不采用。单文件失败会污染整体 lease/retry，并削弱 document/version/job 的独立性。

### 批次原子成功或全部回滚

不采用。外部 storage、Redis、embedding 和 Qdrant 不支持廉价的全局原子事务，且用户更需要保留已成功资料。

### 取消时删除已成功资料

不采用。取消和删除是不同用户意图，合并会造成意外数据丢失。

## 7. 生效条件

与 Spec 002 一并人工接受后生效。实现必须先通过重复幂等键、部分失败、API 中断、retry/cancel race、stale batch 和摘要重算测试。

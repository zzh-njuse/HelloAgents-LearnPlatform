# ADR 002：Ingestion Job、队列、幂等与重试

状态：已接受
接受日期：2026-07-11
日期：2026-07-11
适用阶段：Platform Stage 2

## 1. 背景

资料解析和 embedding 是长任务，不能占用 API 请求。Redis 可能丢消息、重复投递或重启，worker 也可能在任意步骤崩溃，因此 Redis job 状态不能作为业务事实。

## 2. 决策

使用 Postgres `ingestion_jobs` 保存权威 job，使用 RQ 作为 Redis 上的非权威传输和 worker 执行框架。RQ message 只携带 `ingestion_job_id`；不把文件路径、正文、凭据或完整配置放入队列 payload。

### 2.1 Job 类型

Slice 1 支持：

- `ingest_document_version`
- `cleanup_document`
- `rebuild_document_index`

### 2.2 状态机

```text
queued
  -> running
  -> succeeded

queued -> queue_failed
queued/running -> failed
queue_failed/failed -> queued (显式 retry，同一 job ID)
running -> retry_wait -> queued (lease recovery 或受控自动重试)
```

终态 `succeeded` 不允许 retry。删除导致未开始 ingestion 不再需要时可进入 `canceled`；运行中的 worker 在提交阶段再次检查 document lifecycle。

### 2.3 提交流程

1. 原始文件先写入同一 storage volume 的临时路径。
2. API 在一个 Postgres 事务中创建 document/version/job，job=`queued`，并将临时文件原子 rename 到最终 URI。
3. API 在事务提交后向 RQ enqueue job ID。
4. enqueue 失败时将 job 标为 `queue_failed`；若 API 在提交后、enqueue 前崩溃，reconciliation 会重新投递长期未被 claim 的 `queued` job。
5. API 返回 document/version/job 的当前权威状态。

不在数据库事务中调用 Redis，避免持锁等待外部服务。

### 2.4 Claim 与 Lease

worker 收到 job ID 后，使用条件更新 claim：只有 `queued/retry_wait` 且 lease 为空或过期的 job 能进入 `running`。记录 `worker_id`、`lease_expires_at`、`heartbeat_at` 和 attempt count。

长步骤定期 heartbeat。worker 崩溃后，reconciliation 将过期 running job 置为 `retry_wait`，再按策略重新 enqueue。RQ 自身的 failed registry 可用于诊断，不能替代这一状态迁移。

### 2.5 幂等边界

- job 使用稳定 UUID 和唯一 `idempotency_key`，建议格式为 `<job_type>:<target_id>:<generation>`。
- chunk 写入以 `(document_version_id, ordinal)` 唯一，并使用稳定 chunk ID。
- Qdrant 只做稳定 point ID upsert。
- worker 在每个外部副作用前后检查 Postgres 状态；已完成步骤不得重复追加。
- 最终 `succeeded` 更新使用当前 attempt/lease 条件，过期 worker 不能覆盖新 attempt。

### 2.6 重试策略

- `queue_failed`：用户或 reconciliation 可立即重试。
- parser 的确定性错误，例如 `unsupported_type`、`ocr_required`、`encrypted_pdf`：默认不可自动重试，但允许配置/文件变化后的显式重试。
- Redis、Qdrant、embedding provider 暂时错误：指数退避自动重试，默认最多 3 attempts。
- 错误对外只返回稳定 code 和安全摘要；完整 traceback 只进入受控服务日志，且不得含正文或凭据。

用户重复点击 retry 必须幂等：若 job 已 queued/running，返回当前状态，不再次 enqueue；若并发请求竞争，由数据库条件更新决定唯一成功者。

## 3. Compose 与 Migration Owner

- 新增 `worker` 服务，共用 API 镜像和 product settings，但执行 RQ worker entrypoint。
- API 容器仍是 Stage 2 的 migration owner。
- worker 必须依赖 API health 或独立 migration completion 条件，不执行 `alembic upgrade`。
- worker 与 API 访问同一 storage volume；Redis 数据丢失后可由 Postgres reconciliation 恢复待执行 job。

## 4. 影响

### 正向

- Redis 清空不会删除业务任务事实。
- 重复消息、重复 retry 和 worker 崩溃可恢复。
- RQ 提供成熟 worker 生命周期，避免手写 Redis blocking queue。

### 成本

- Postgres 状态与 RQ registry 可能短暂不一致，需要 reconciliation。
- lease/heartbeat 和条件更新增加实现与测试复杂度。
- Compose 增加 worker，开发环境资源占用上升。

## 5. 未采用方案

### Celery

暂不采用。功能完整但配置、结果后端和运维面超过 Slice 1 需求；RQ 足以承担单队列 self-host worker。

### 手写 Redis List/Stream worker

不采用。连接恢复、worker 生命周期和失败 registry 不值得从零实现。

### Redis/RQ job 作为唯一状态

不采用。无法满足 Postgres 事实来源、备份恢复和用户可见状态要求。

### 每次 retry 创建新业务 job

不采用为默认行为。它会模糊一个资料版本的处理身份；同一 job 增加 attempt 更利于审计。人工重新处理策略变化时，可显式创建新的 generation。

## 6. 生效条件

与 Spec 001 一并确认后生效。实现前需用并发测试证明 claim、重复 enqueue、重复 retry、过期 lease 和旧 worker 提交均符合状态机。

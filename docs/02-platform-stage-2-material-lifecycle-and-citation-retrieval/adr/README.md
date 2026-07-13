# Stage 2 ADRs

已接受：

- [ADR 001](001-document-authority-versioning-deletion-and-rebuild.md)：资料、版本、chunk、删除和重建。
- [ADR 002](002-ingestion-job-queue-idempotency-and-retry.md)：job、RQ、幂等、lease 和重试。
- [ADR 003](003-parser-embedding-qdrant-and-product-adapters.md)：parser、embedding、Qdrant 和 product adapter。

Slice 2 已接受并落实：

- [ADR 004](004-batch-ingestion-ownership-idempotency-and-cancellation.md)：批量入库的所有权、幂等、部分失败和取消。
- [ADR 005](005-cited-answer-generation-and-agent-boundary.md)：带引用回答、generation provider、持久化与 Agent 边界。
- [ADR 006](006-parser-resource-budget-and-isolation.md)：parser 隔离、分层资源预算、超限和并发语义。

每项不可逆或跨模块决策使用独立 ADR；不能以代码实现反向定义这些合同。

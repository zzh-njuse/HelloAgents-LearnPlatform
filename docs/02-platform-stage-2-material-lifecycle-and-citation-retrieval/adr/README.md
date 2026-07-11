# Stage 2 ADRs

实现前至少需要确认：

- 资料、版本、chunk、job 与引用的权威数据边界。
- 原始文件存储、软删除、清理和 Qdrant 索引重建语义。
- ingestion job 的幂等键、状态迁移、重试和 queue failure 恢复方式。
- parser、embedding provider、collection 命名、worker 与 API 的依赖边界。

每项不可逆或跨模块决策使用独立 ADR；不能以代码实现反向定义这些合同。

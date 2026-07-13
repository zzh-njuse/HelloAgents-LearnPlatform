# ADR 001：资料权威数据、版本、删除与索引重建

状态：已接受
接受日期：2026-07-11
日期：2026-07-11
适用阶段：Platform Stage 2

## 1. 背景

资料同时存在于 Postgres、文件存储和 Qdrant。若三者都被当作事实来源，上传失败、删除失败或索引漂移时就无法判断真实状态。Stage 1 已接受 Postgres 权威、storage 保存文件字节、Qdrant 可重建的原则；Stage 2 必须把原则落实为字段、事务和恢复顺序。

## 2. 决策

采用三层所有权：

| 组件 | 拥有的数据 | 不拥有的数据 |
|---|---|---|
| Postgres | document/version/job 生命周期、chunk 正文与定位、删除状态、trace | 原始大文件字节、向量 |
| Local storage | 原始文件、规范化解析全文和可选 parse artifact | 业务可见性、当前版本、job 状态 |
| Qdrant | embedding 与最小候选定位 payload | 唯一正文、唯一删除状态、当前版本事实 |

### 2.1 Document 与 Version

- `source_document` 是用户可操作身份，始终属于一个 workspace。
- `document_version` 是不可变上传事实；新版本创建新行，不覆盖原文件、hash 或 parser/embedding 标识。
- `current_version_id` 只在对应 version 成为 ready 后切换。
- Slice 1 不提供“覆盖上传”，只创建首个 version；模型从第一天支持后续版本化。

### 2.2 Chunk 正文

chunk 正文保存在 Postgres。理由：

- citation 响应需要稳定、低复杂度的权威回读；
- 删除过滤和 workspace 校验必须在同一事实层完成；
- Qdrant payload 不能成为正文唯一副本；
- 从 storage 解析全文重建 chunk 仍然可行，但在线查询不应依赖文件偏移读取。

storage 中同时保存规范化解析全文，作为审计、重新切块和重建输入。该重复是有意的：Postgres chunk 面向在线引用，storage 全文面向可重建性。

### 2.3 Storage URI

只保存服务端生成的相对 URI：

```text
workspaces/<workspace_id>/documents/<document_id>/versions/<version_id>/original.<ext>
workspaces/<workspace_id>/documents/<document_id>/versions/<version_id>/parsed/content.md
```

写入先进入同一文件系统下的临时路径，`fsync` 后原子 rename。数据库不得保存宿主机绝对路径，下载或解析不得接受用户传入 storage URI。

### 2.4 删除

采用权威软删除加异步清理：

1. Postgres 将 document 置为 `deleted` 并创建 cleanup job。
2. 默认列表和检索在事务提交后立即排除该 document。
3. cleanup 删除 Qdrant points。
4. cleanup 按保留策略删除 storage 目录，并记录完成状态。
5. cleanup 失败不恢复 document 可见性，只允许重试。

Slice 1 默认不提供恢复已删除资料。物理删除完成前，管理员仍可通过数据库备份恢复，但这不是产品 API 合同。

### 2.5 Qdrant Collection 与 Point

- 使用单一产品 collection，建议默认名 `learn_platform_source_chunks_v1`。
- 每次检索必须带 `workspace_id` filter。
- point ID 使用 chunk UUID；payload 仅包含 workspace/document/version/chunk ID、heading path、content hash 和 schema version。
- 不在 payload 保存唯一 chunk 正文。
- collection 维度或距离不兼容时启动失败并提示执行显式 rebuild；禁止运行时自动删除 collection。

### 2.6 索引重建

重建只读取 Postgres 中 active document 的 ready current version 和 chunk 正文，使用当前显式 embedding 配置生成向量，以稳定 chunk ID upsert。重建过程创建新版本 collection 或先清空目标 collection，由运维命令显式触发；不能由普通查询自动触发破坏性重建。

## 3. 一致性边界

Postgres 与 storage/Qdrant 之间不使用分布式事务。系统通过“权威状态先行、派生操作可重试”获得最终一致性：

- 上传原文件成功但事务失败：补偿删除临时/孤儿文件。
- chunk 已提交但 Qdrant 失败：version 不进入 ready，retry 重复 upsert。
- Postgres 已 deleted 但 Qdrant 删除失败：在线回读过滤保证不可见。
- Qdrant 丢失：从 Postgres/storage 全量重建。

## 4. 影响

### 正向

- 任意失败后都能回答“真实业务状态是什么”。
- citation 不依赖 Qdrant payload 正文。
- 删除立即生效，物理清理可延后。
- 未来 object storage 和 collection rebuild 不改变 API 合同。

### 成本

- Postgres 与 storage 会保留部分重复文本。
- 查询必须做 Qdrant 候选到 Postgres 的批量回读。
- 需要 orphan storage reconciliation 和索引重建工具。

## 5. 未采用方案

### Qdrant 保存唯一 chunk 正文

不采用。删除、引用和恢复将依赖派生索引，违反既有数据原则。

### Postgres 保存原始文件 blob

暂不采用。会扩大数据库备份、迁移和 IO 压力；local/object storage 更适合原始字节。

### 物理删除同步完成后才返回

不采用。Qdrant/storage 短暂故障会阻塞用户删除，并可能错误恢复可见性。

### 自动删除维度不匹配的 collection

不采用。现有 framework store 的这种便利行为对产品数据过于危险，产品 adapter 必须显式失败。

## 6. 生效条件

与 Spec 001 一并确认后生效。实现必须包含删除后回读过滤、重复 upsert 和 collection 丢失重建测试。

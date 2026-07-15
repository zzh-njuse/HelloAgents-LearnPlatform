# ADR 003：Tutor Session、上下文快照与删除事实

状态：已接受（2026-07-15 人工 Gate）

日期：2026-07-15

## 1. 决策摘要

建议由 Product Postgres 拥有 Tutor Session、Turn、Answer Block 和 Citation。Session 固定 Course Version；每个 Turn 再固定 scope 与 Lesson Version。对话 history 只是用户可见、可删除的短期上下文，不写入 framework SessionStore，也不提升为长期 Memory。

删除采用 `active -> deleting -> deleted`：立即隐藏并阻止新 turn，取消 active turn，随后硬删除 session 正文、citation 和关联 Tutor trace。删除失败保留可重试的权威状态。

## 2. 背景

prototype session 是进程内 Agent 字典；framework SessionStore 是本地 JSON 快照；两者都缺少 workspace/version 关系、并发、删除和迁移合同。Stage 4 才负责可管理的长期 Memory，因此 Slice 2 不能用 Memory 概念掩盖普通聊天记录。

## 3. 决策

### 3.1 数据所有权

- `tutor_sessions` 拥有课程版本锚点、生命周期和外部确认 snapshot。
- `tutor_turns` 拥有 user message、scope/history snapshot、状态和结构化 final answer。
- `tutor_turn_citations` 拥有 block 到 document version/chunk 的权威定位。
- Redis 只负责 turn 投递和短期流式事件；本地 JSON/file memory 禁止进入产品主路径。

### 3.2 版本锚点

- 创建 session 时固定 `workspace_id`、`course_id`、`course_version_id`。
- lesson scope 的每个 turn 固定 `section_id`、`lesson_id`、`lesson_version_id`。
- 新 Course Version 或 Lesson Version 不修改历史 session/turn。
- 旧版本 session 可以查看，但 Course 不再以该版本为 active 后拒绝新 turn；用户应基于新 active version 创建 session。来源快照状态仍决定历史 citation 是否可用。

### 3.3 短期 history

- 默认只取最近 8 个成功 turn，且总 history 不超过 6,000 estimated tokens。
- 以完整 turn 为单位从最旧开始裁剪，不截成残缺 user/assistant 对。
- 失败、取消和 deleting turn 不进入后续 history。
- Slice 2 不生成隐藏摘要、不跨 session 召回、不更新 UserModel/掌握度。

### 3.4 并发与幂等

- 一个 session 最多一个 active turn，由数据库约束和行锁共同保证。
- Turn ordinal 在 session 行锁内递增。
- `Idempotency-Key` 在 session 内唯一；同 key 不同 payload 返回冲突。
- retry 复用原消息、scope 和 history boundary，仅增加 attempt/run。

### 3.5 删除

1. API 把 session 置为 `deleting`，默认查询立即排除，并请求取消 active turn。
2. cleanup 删除 turn citations、turns、Tutor Agent tool calls/runs 和 session。
3. provider 迟到结果在提交前看到 deleting/cancel 状态，不得复活数据。
4. cleanup 失败不回滚为 active；由 reconciler 或显式 retry 完成。

不保留消息 tombstone。未来 Quality & Cost 需要长期聚合时，只能保存无法回连正文/session 的聚合指标，并另行 ADR。

## 4. Schema 约束建议

- 所有 Tutor 表保留 `workspace_id` 并建立 workspace/session/status 索引。
- session 的 course/version 外键必须属于同一 workspace/course；服务层和 migration 测试共同验证。
- turn 的 lesson/version 必须属于 session Course Version。
- answer blocks 使用受 schema 限制的 JSON；citation 使用规范化表，不只保存模型 JSON。
- Tutor run owner 与 course generation job owner 二选一，使用 check constraint 保证恰好一个 owner。

## 5. 敏感信息

Session 会保存用户问题和最终回答，这是为了刷新恢复而新增的敏感事实。它们：

- 不进入普通日志、Agent trace、Redis queue payload 或错误正文；
- 不通过 system info/readiness 暴露；
- 只在 workspace/session 过滤通过后由 API 返回；
- 随 session 删除，不以“审计”为理由无限保留。

## 6. 未采用方案

### 直接复用进程内 prototype session

拒绝。重启丢失、无法并发控制、没有 workspace/version/delete 合同。

### 使用 framework SessionStore JSON

拒绝。文件包含完整 history 和工具缓存，不是 Postgres 产品事实，也无法可靠 migration/隔离/清理。

### Session 始终跟随 active Course Version

拒绝。会让同一对话的证据范围静默漂移，历史回答不可复现。

### 在 Slice 2 建长期 Memory 或自动摘要

拒绝。缺少可查看、纠正、删除、提升和 eval 合同，属于 Stage 4。

### 只做软删除并永久保留正文

拒绝。用户看到“删除对话”时不应只隐藏敏感消息。

## 7. 影响

正向：刷新恢复、版本可复现、删除可验证、history 与长期 Memory 明确分离。

成本：新增 migration、cleanup/reconciliation、敏感正文保护和统一 AgentRun owner 约束；旧 session 在新版本激活后需要明确 UI 提示。

## 8. 生效条件与人工 Gate

本 ADR 只有在以下选择被人工接受后生效：

1. Session 固定 Course Version，Turn 固定 Lesson Version/scope。
2. history 默认 8 个成功 turn / 6,000 tokens，且不做隐藏摘要。
3. 一个 session 只允许一个 active turn。
4. Session 删除最终硬删除 Tutor 正文、citation 和关联 run/tool trace。
5. Session history 不等于长期 Memory，Slice 2 不更新掌握度或学习画像。

# Spec 002：Course Reader 内的受控 Tutor

状态：已接受（2026-07-15 人工 Gate）

日期：2026-07-15

适用阶段：Platform Stage 3 Slice 2

## 1. 评审结论摘要

本规格建议在 Course Reader 内交付第一条 Tutor 纵向路径：用户基于当前激活课程和已发布课节创建一个可恢复 session，连续提问；每个 turn 固定课程/课节版本，通过受控证据工具生成带引用回答，并支持安全流式显示、取消、失败重试和 session 删除。

建议把 session history 定义为 Postgres 中用户可见、可删除的短期对话记录，而不是 Stage 4 长期 Memory。Tutor 采用新的受控领域 adapter，不直接复用 `LearningAgent`；它只拥有证据检索和结构化回答提交工具，不拥有 Skill、MCP、网页、文件、Todo、Memory、进度更新或其他 Agent。

本次需要人工确认的核心选择是：session 的版本锚点、短期历史保留、每 session 外部处理确认、5 step/3 次检索预算、异步 turn + SSE 传输方案，以及删除是否级联清除 Tutor trace。

## 2. Goal、Context、Constraints、Done when

| 项目 | 内容 |
|---|---|
| Goal | 用户在 Reader 当前课程/课节内获得连续、带引用、可拒答且可恢复的辅导 |
| Context | Stage 2 已有权威 RAG/citation；Slice 1 已有版本化课程、来源快照、Reader 和最小 Agent trace |
| Constraints | Postgres 权威；workspace/version scope；无长期 Memory、Skill、MCP、自主多 Agent；不直接复用 prototype session |
| Done when | session/turn 主路径、引用与拒答、取消/重试/重连/删除、focused tests、migration、Web build、Compose、eval 和人工 Chrome smoke 均有记录 |

## 3. 用户价值与成功标准

- Tutor 位于 Course Reader 内，默认聚焦用户正在阅读的课节，不成为无上下文聊天首页。
- 刷新或重新进入 Reader 后可以恢复 session 和已完成 turn。
- 每个事实性回答 block 都能定位到 Course Version 来源快照内的 citation；资料不足时明确拒答。
- 课程激活版本变化不会改写旧 session；用户可以继续查看旧 session或基于新版本创建新 session。
- 同一 session 同时只允许一个 active turn，避免并发 history 分叉。
- 断线不丢失已提交问题或最终回答；SSE 丢失只影响临时动画，不影响 Postgres 事实。
- 用户可以取消或重试失败 turn，并可以删除整个 Tutor session 及其消息、citation 和关联 Tutor trace。

## 4. 范围

### 4.1 范围内

- Reader 内 Tutor 面板。
- Postgres session、turn、answer block、citation 和状态。
- lesson scope 与 course scope 两种显式模式；默认 lesson scope。
- 短期多轮 history、刷新恢复、session 列表和删除。
- Tutor turn 异步执行、SSE 安全事件、取消和显式重试。
- 受控 Tutor Agent、证据工具、结构化回答和最小 run/tool trace。
- 固定 eval 和一组无敏感资料的人工 Chrome smoke。

### 4.2 明确不做

- Working/Episodic/Semantic 长期 Memory、学习画像、掌握度和复习推荐。
- 自动总结并提升为长期记忆、跨 session 个性化或跨课程历史召回。
- Skill、MCP、网页搜索、文件系统、代码执行、Todo 或其他 Agent。
- 练习、评分、rubric、学习事件或课程进度写入。
- 语音、图片、多模态、公开分享和多用户权限。
- 通用聊天首页、跨 workspace 问答或后台主动发起 Tutor 消息。

## 5. 核心不变量

1. Session 固定 `workspace_id + course_id + course_version_id`；Course Version 不随 active pointer 漂移。
2. 每个 Turn 固定 `scope`，并在 lesson scope 下固定 section、lesson 和已发布 lesson version。
3. history 是对话上下文，不是事实证据；citation 只能来自当前 turn 的产品 evidence ledger。
4. Qdrant 只召回候选；Postgres 必须按精确 course source versions 回读。
5. Redis/SSE 不是事实来源；最终 turn、answer blocks、citation 和状态原子提交到 Postgres。
6. provider 失败、资料不足或取消时不提交部分正式回答。
7. 模型不能扩大 workspace、course、source、version 或 scope。

## 6. 用户流程

### 6.1 创建或恢复 session

1. 用户在已激活课程的 Reader 打开 Tutor 面板。
2. Web 默认选择当前课节的 `lesson` scope，也允许用户显式切换到 `course` scope。
3. 首次创建 session 时显示 provider、固定 Course Version、来源数量和资料片段/问题/短期历史将外发的提示。
4. 用户确认后创建 session；确认只覆盖该 session 固定的 provider 和 Course Version。
5. 刷新页面后 Web 列出该 Course Version 的 active session，并恢复已完成 turn。

### 6.2 提问与流式显示

1. Web 以 `Idempotency-Key` 创建 Turn；API 先持久化 user message、scope snapshot 和 `queued` 状态，再投递 Tutor queue。
2. Web 连接该 Turn 的 SSE endpoint；只接收状态、回答 delta、citation available、完成、失败和 heartbeat。
3. Worker 加载有限 history、当前课节结构和 evidence scope，执行 Tutor。
4. 成功后在一个事务中保存 answer blocks/citations、结束 Agent Run，并把 Turn 标记为 `succeeded`。
5. Web 以 GET 返回的最终 Turn 为权威；SSE delta 仅用于生成过程显示。

### 6.3 取消、失败和重试

- 用户取消会把 active turn 置为 `cancel_requested`；worker 在 provider/tool/提交边界检查。
- provider 不可中断时允许调用返回，但取消后不得提交回答。
- retry 复用原 user message、scope snapshot、history boundary 和外部确认，创建新 attempt/Agent Run，不扩大来源。
- 同一 session 有 active turn 时新建 turn 返回 409；失败或取消后可重试或开始新 turn。

### 6.4 版本变化与来源降级

- 课程激活新版本后，旧 session 仍可只读查看；Web 提示它绑定旧版本，并提供创建新 session 的动作。
- lesson 发布新版本后，已有 turn 不改变；新 turn 必须显式使用当前 session 所属 Course Version 中用户选择的已发布 Lesson Version。
- 任一固定来源不再 active/current/ready 时，新的 turn 以 `source_snapshot_stale` 拒绝；历史回答保留但 citation 标记不可用。

### 6.5 删除

- 删除 session 后立即从默认查询隐藏、拒绝新 turn，并请求取消 active turn。
- cleanup 最终硬删除 session 的 user/assistant 正文、answer blocks、citation 和 Tutor run/tool trace。
- 删除失败保留 `deleting` 权威状态并可重试；不把“隐藏”冒充已物理删除。

## 7. 状态模型

Session：

```text
active -> deleting -> deleted
```

Turn：

```text
queued -> running -> succeeded
                  -> retry_wait -> running
                  -> failed
queued/running/retry_wait -> cancel_requested -> canceled
```

## 8. API 草案

所有路径位于 `/api/v1/workspaces/{workspace_id}` 并强制 workspace 关系过滤。

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/courses/{course_id}/tutor-sessions?course_version_id=` | 列出当前版本 session 摘要 |
| `POST` | `/courses/{course_id}/tutor-sessions` | 创建固定 Course Version 的 session并记录外部确认 |
| `GET` | `/tutor-sessions/{session_id}` | 返回 session、turn、answer blocks 和 citation |
| `DELETE` | `/tutor-sessions/{session_id}` | 进入 deleting、取消 active turn并安排清理 |
| `POST` | `/tutor-sessions/{session_id}/turns` | 幂等创建并排队一个 turn，返回 202 |
| `GET` | `/tutor-turns/{turn_id}` | 返回权威状态和最终回答 |
| `GET` | `/tutor-turns/{turn_id}/events` | SSE 安全事件；完成后返回最终状态事件 |
| `POST` | `/tutor-turns/{turn_id}/cancel` | 请求取消 |
| `POST` | `/tutor-turns/{turn_id}/retry` | 原上下文显式重试 |

Session create 至少包含 `course_version_id` 和 `external_processing_ack=true`。Turn create 至少包含 `question`、`scope`，lesson scope 还包含 `section_id`、`lesson_id`、`lesson_version_id`；这些 ID 必须由服务端验证为同一 Course Version。

## 9. 数据模型草案

### `tutor_sessions`

保存稳定 ID、workspace/course/course version、状态、provider/model snapshot、外部确认时间、最后 turn ordinal、创建/更新时间和删除状态。不保存长期 memory 或隐藏摘要。

### `tutor_turns`

保存 session、ordinal、attempt/status、幂等键、user message、scope 与 section/lesson/version snapshot、history boundary、结构化 answer blocks、错误码、token/延迟和时间。一个 session 最多一个 active turn。

### `tutor_turn_citations`

保存 turn/block key、citation ID、document/version/chunk 和定位信息。citation 必须属于 Session Course Version 的来源快照。

### `agent_runs/agent_tool_calls`

扩展 run owner，使每个 run 恰好属于 Course Generation Job 或 Tutor Turn；Tutor 删除时级联删除相关 Tutor run/tool trace。trace 仍不保存消息、原始 query、evidence、prompt 或 provider 响应。

## 10. Context 与回答合同

- 推荐默认 history 上限：最近 8 个成功 turn，且序列化后不超过 6,000 estimated tokens；先按完整 turn 从旧到新丢弃，不做隐藏 LLM 摘要。
- 当前 lesson 的标题、目标、已发布正文结构可作为教学上下文；其 citation chunk 可预载入当前 evidence ledger。
- history 中的 assistant answer 和 citation 不能自动成为当前 turn 的事实证据。
- 回答由最多 20 个结构化 block 组成：`explanation`、`example`、`check_question`、`limitation`。事实性的 explanation/example 必须有 citation；教学追问可无 citation但不能引入新事实。
- 资料不足由服务端返回稳定 refusal，不让模型用常识补齐。

## 11. 推荐预算

| 预算 | 草案默认值 | 理由 |
|---|---:|---|
| Agent decision step | 5 | 允许 3 次检索、一次提交和一次修复 |
| evidence search | 3 | 单 turn 比课程大纲窄，但允许补充与核对 |
| 每次 evidence | 5 条 | 沿用现有相关性与回读模式 |
| evidence 总预算 | 8,000 estimated tokens | 低于课程生成的 12,000，控制交互延迟 |
| history | 8 个成功 turn / 6,000 tokens | 支持指代连续性，不形成无限 history |
| 输出 | 2,000 tokens | 支持解释、示例和检查问题 |
| generation provider 调用 | 正常 2 次，最坏 3 次 | 查询规划 + 回答 + 可选一次修复；不是每 step 一次模型调用 |

所有检索和提交均消耗 step；用满 3 次检索后仍保留提交与一次修复。具体 provider wall-clock timeout 在实现计划前用无敏感 fixture 实测，但不能改变权限和来源边界。

名词、调用次数和人民币量级见 [Tutor 名词与成本模型](../TUTOR_TERMS_AND_COST_MODEL.md)。

## 12. SSE 合同

允许事件：`turn.queued`、`turn.started`、`turn.progress`、`answer.delta`、`citation.available`、`turn.completed`、`turn.failed`、`turn.canceled`、heartbeat。

禁止发送：隐藏思考、system prompt、history 原文回显、原始工具 query/参数、evidence 正文、provider 原始错误、内部 URL、绝对路径和 traceback。

Redis 可保存短期、限长事件流以支持重连；若事件已过期，客户端回退到 GET Turn。最终回答只以 Postgres 提交为准。

## 13. 失败矩阵

| 错误码 | 用户行为 | 重试 |
|---|---|---|
| `course_version_inactive` | 创建时所选版本不再是当前 Reader 版本 | 刷新或创建明确的旧版只读 session |
| `lesson_version_mismatch` | lesson 不属于固定 Course Version | 刷新 scope |
| `source_snapshot_stale` | 来源已变化或删除 | 新课程版本/session |
| `insufficient_evidence` | 当前资料不足 | 调整问题/scope或补资料 |
| `active_turn_exists` | session 已有运行 turn | 等待或取消 |
| `generation_provider_unconfigured` | provider 未配置 | 配置后重试 |
| `generation_provider_unavailable` | provider 暂不可用 | 受 attempt 上限重试 |
| `agent_step_budget_exceeded` | 超出预算 | 默认人工检查 |
| `invalid_agent_artifact` | 回答 schema/citation 修复后仍无效 | 显式重试 |
| `generation_canceled` | 用户取消或 worker 丢失租约 | 显式重试 |
| `event_stream_unavailable` | 临时流不可用 | GET Turn 继续观察 |

## 14. 安全与隐私

- user message 和 final answer 是敏感产品正文，只进入 Postgres session/turn，不进入普通日志、trace 或 SSE 元数据。
- 每 session 的外部确认覆盖固定 provider/model 和 Course Version；provider/model 或版本改变必须创建新 session 并重新确认。
- 输入长度、session turn 数、history/evidence/output token、step、timeout、并发和 Redis event retention 均设硬上限。
- 当前单用户 self-host 不等于可忽略 workspace 过滤。
- prompt injection eval 覆盖资料、历史 user message 和历史 assistant answer 三个输入面。

## 15. Web 体验

- Tutor 是 Reader 主区旁的可收起面板；窄屏位于课节正文之后，不遮挡阅读。
- 顶部始终显示当前 scope、固定课程版本、来源降级和运行状态。
- citation 复用 Reader 的可读来源表现，按“文件名 > 章节路径 > 第 N-M 页”显示已有信息，不向用户暴露 evidence ID、chunk UUID 或字符偏移；本 Slice 不要求跳转、高亮原文。
- “当前课节”只显示与当前选中 `lesson_version_id` 相同的 lesson scope 历史 Turn；“整门课程”只显示 course scope 历史 Turn，不提供混合全部历史入口。
- 流式 delta 使用稳定高度和自动滚动边界；用户主动向上阅读后不强制拉回底部。
- session 切换、取消、重试和删除使用明确命令；不暴露开发者 tool trace。

## 16. 验证与 Eval

- Migration：从 `0011` 升级、约束、索引、删除级联和 downgrade/upgrade。
- API：workspace 隔离、版本/scope 校验、幂等、单 active turn、删除与错误映射。
- Worker：claim/lease、重试、取消、迟到响应、重复投递和最终原子提交。
- Agent：工具白名单、5/3 预算、citation ledger、一次修复、history 注入攻击。
- SSE：事件白名单、重连、事件过期回退、断线和无敏感字段。
- Eval：章节内问题、跨章节 scope、无证据拒答、来源降级、引用有效性、历史污染、token/延迟。
- 实际栈：Compose、ready、Web 200、synthetic Tutor E2E。
- 人工 Chrome smoke：创建/恢复 session、连续两轮、citation、取消/重试、刷新、版本变化和删除。

## 17. 建议实现顺序

1. migration 与 ORM；session/turn service 和删除语义。
2. 同步 CRUD、scope/citation 校验和 fake turn lifecycle。
3. Tutor queue/worker、lease/retry/cancel 和 Agent trace owner 泛化。
4. `TutorEvidenceSearch`、领域 adapter、artifact validation 和 fixed eval。
5. SSE 安全事件与断线回退。
6. Reader Tutor 面板。
7. focused tests、migration、Compose、人工 smoke；人工批准后 OCR。

## 18. 人工 Gate

接受本 Spec 前需逐项确认：

1. Slice 2 交付 Reader 内可恢复多轮 Tutor，而不是只扩展单轮 `/rag/answer`。
2. Session 固定 Course Version；每 Turn 固定 lesson version/scope，版本变化不静默漂移。
3. history 是可见、可删除的短期对话，不是长期 Memory；默认最近 8 个成功 turn / 6,000 tokens，不做隐藏摘要。
4. Tutor 采用 5 step / 3 次检索、8,000 evidence tokens、2,000 output tokens 的草案默认预算。
5. 每 session 确认一次固定 provider/model/Course Version 的外部处理；新版本或 provider 重新确认，不要求每 turn 重复弹窗。
6. Turn 使用 Postgres 权威异步状态 + Redis queue/短期 SSE event；SSE delta 不是事实来源。
7. 删除 session 最终硬删除消息、回答、citation 和关联 Tutor trace；失败保持 deleting 并可重试。
8. Skill、MCP、长期 Memory、练习、进度写入和自主多 Agent 不进入 Slice 2。

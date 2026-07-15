# ADR 004：受控 Tutor Runtime、队列、流式传输与 Trace

状态：已接受（2026-07-15 人工 Gate）

日期：2026-07-15

## 1. 决策摘要

建议新增 `academic_companion` Tutor adapter，复用 `hello_agents` 的受控 runtime 基础，但由 Product app 拥有 scope、工具、queue、provider、校验、SSE 和持久化。Tutor 只拥有 `TutorEvidenceSearch` 与 `SubmitTutorAnswer`。

每个 Turn 建议最多 5 个 decision step、3 次检索、8,000 evidence tokens、2,000 output tokens。Turn 先在 Postgres 持久化，再由 Redis queue 投递；Redis 短期事件流承载安全 SSE，最终回答仍原子提交 Postgres。

## 2. 背景

Slice 1 已验证受控角色、产品证据工具、结构化提交和最小 trace。Tutor 与课程生成不同：它需要低延迟、多轮 context、流式反馈和 session 删除，但不能因此直接转发 prototype/framework event 或引入其 Memory/Skill/Todo 副作用。

## 3. Runtime 与工具决策

### 3.1 Tutor adapter

- 在 `academic_companion` 新建 Tutor 请求/回答 artifact 与 prompt adapter。
- 每个 attempt 创建全新 runtime；history 由产品按 ADR 003 装配，不恢复 framework session。
- runtime 禁用 framework SessionStore、Memory、Skill、MCP、文件、shell、Todo、subagent 和通用 RAG。

### 3.2 `TutorEvidenceSearch`

模型只提供不超过 300 字符的语义 query。产品固定：

- workspace 与 Session Course Version；
- 精确 Course Version source document versions；
- 当前 turn 的 lesson/course scope；
- Stage 2 相关性门禁与 Postgres 权威回读；
- 每次最多 5 条、每 attempt 最多 3 次、总 evidence 8,000 estimated tokens。

当前 Lesson Version 已有 citation 对应的 chunk 可以预载入 evidence ledger；预载不扩大来源，也不计模型工具调用。history 不能签发 evidence ID。

### 3.3 `SubmitTutorAnswer`

提交最多 20 个 block。`explanation`/`example` 必须引用当前 evidence ledger；`check_question`/`limitation` 可不引用但不能声明新事实。首次提交无效时，只在剩余 step 内允许一次结构修复，不能检索新证据或放宽 citation。

证据不足时由产品生成稳定 refusal；Tutor 不得无引用自由回答。

## 4. 预算与停止

- 5 个 decision step、3 次 evidence search；搜索和提交都消耗 step。
- 8,000 estimated evidence tokens、2,000 output tokens。
- history 预算由 ADR 003 控制，不与 evidence 混为一类。
- 达到 step/tool/token/wall-clock 任一上限立即结束，不 fallback provider/model。
- 取消、lease 和 session deleting 在 provider、tool、SSE publish 和最终提交边界检查。

采用 5/3 而不是 Lesson Writer 的 4/3，是为了让 Tutor 在用满三次检索后仍可提交并进行一次结构修复；这不是允许额外开放式推理。

与 Slice 1 相同，逻辑 step 不等于 generation provider 调用。推荐实现先用一次有界规划调用产生 1 至 3 条 query，再执行本地工具，随后一次回答调用；只有校验失败才增加一次修复调用。因此正常最多 2 次、最坏 3 次 DeepSeek 调用，不采用每个 ReAct step 都重新调用模型的开放循环。

## 5. Queue 与幂等

- `tutor_turns` 自身是 Postgres 权威 job；不再建立含义重复的 Tutor Job 表。
- Redis queue payload 只包含 turn ID 和 attempt，不包含问题、history 或 evidence。
- 使用独立 Tutor queue/concurrency/timeout 配置，避免长课程生成阻塞交互 turn。
- claim/lease/heartbeat/retry/cancel/reconciler 沿用 Slice 1 模式，但状态和错误码属于 Tutor Turn。
- 最终 answer blocks、citations、AgentRun 完成和 Turn succeeded 在仍拥有 lease 时原子提交。
- 重复消息、过期 worker 和迟到 provider 响应不得创建第二份正式回答。

## 6. SSE 决策

Redis 短期、限长 event stream 只用于传输体验：

- 允许 coarse progress、answer delta、citation available、terminal status 和 heartbeat。
- 不发送 thinking、工具 query/参数、evidence、history、prompt、provider 原始错误或 traceback。
- event 使用递增序号；客户端可携带 last event ID 重连。
- stream 丢失或过期时，SSE 返回当前 Postgres 状态并提示客户端 GET Turn。
- 客户端断线不自动取消 Turn；用户必须显式取消。这样刷新/网络抖动不会浪费已产生的 provider 调用。

回答 delta 不写入 Postgres；只有校验通过的完整 artifact 成为正式回答。provider 原始 token 不直接转发，`answer.delta` 只能来自已经完成结构解析且 citation ID 已通过当前 evidence ledger 校验的完整 block。无法安全增量校验时只发送 coarse progress 和最终回答事件。

## 7. 外部处理确认

建议从 Slice 1 的“每个新 generation job 确认”调整为“每个 Tutor Session 确认一次”，因为多轮交互需要可用性，且 Session 已固定 provider/model 与 Course Version。重试和后续 turn 不扩大已确认范围。

出现以下任一变化必须新建 session 并重新确认：Course Version、provider/model、外发数据类别或 scope 权限实质变化。Web 在 Tutor 面板持续显示 provider 与外部处理状态，而不是只在首次弹窗展示。

## 8. Trace

- 复用统一 `agent_runs/agent_tool_calls`，但 run owner 泛化为 course job 或 Tutor turn 二选一。
- run 保存 role、attempt、runtime/prompt schema version、provider/model、状态、step/token/延迟和错误码。
- tool call 保存顺序、工具名、query hash、结果数量、延迟、状态和错误码。
- 不保存消息、answer 正文、原始 query、history、evidence、prompt、provider response 或 SSE delta。
- Tutor session 删除时删除其 Tutor run/tool trace；失败 attempt 的 tool trace 是否独立提交应在实现中通过独立小事务保证，但不能让 trace 失败阻断用户正文删除。

## 9. 安全边界

- 当前 question 是任务输入，但无权改变 system、工具白名单、scope 或输出 schema。
- 资料、历史 user message、历史 assistant answer 和课程正文分别标注为不可信数据。
- 产品工具忽略模型提供的任何 workspace/source/version filter。
- 对外 API/SSE 只返回稳定错误码和安全中文摘要。
- Redis key、queue、event payload 和日志不得包含正文或 provider key。

## 10. 未采用方案

### 直接复用 `LearningAgent`

拒绝。它自带 prototype RAG、Memory、UserModel、Skill、Todo 和进度副作用。

### API 请求内同步执行并直接 SSE

不建议。断线会把执行生命周期绑定到 Web 连接，难以安全恢复、重试和区分迟到提交。

### 把每个 token 持久化到 Postgres

拒绝。写放大明显，部分输出也不应成为正式事实。

### Redis Pub/Sub 作为唯一流来源

拒绝。断线即丢事件且无法恢复；采用短期 Redis Stream 加 Postgres terminal fallback。

### 向前端转发 framework 全部 StreamEvent

拒绝。可能暴露 thinking、工具参数、evidence 和内部异常。

### 每 turn 重复外部确认弹窗

不建议。不会实质缩小已固定的 session scope，却破坏连续学习；改为 session snapshot 确认。

## 11. 影响

正向：交互执行可恢复、SSE 不拥有事实、工具和 scope 可审计、刷新不断开后台 turn。

成本：新增独立 Tutor queue、Redis event stream、SSE client、AgentRun owner migration 和失败 trace 小事务；部署与测试范围扩大，必须进入 OCR 与人工浏览器 gate。

## 12. 生效条件与人工 Gate

本 ADR 只有在以下选择被人工接受后生效：

1. 新建受控 Tutor adapter，不复用 `LearningAgent` 实例/session。
2. 工具仅 `TutorEvidenceSearch` 和 `SubmitTutorAnswer`。
3. 默认预算 5 step / 3 search / 8,000 evidence / 2,000 output。
4. Postgres Turn 权威，Redis queue + 短期 event stream；客户端断线不自动取消。
5. SSE 只发送安全白名单事件，最终完整 artifact 才进入 Postgres。
6. 外部处理按固定 provider/model/Course Version 的 session 确认，而不是每 turn 弹窗。
7. Tutor run/tool trace 不保存正文，并随 session 删除。

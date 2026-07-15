# ADR 006：自适应课节编排与独立预算归属

状态：已接受（2026-07-15 人工 Gate）

2026-07-15 补充决策：已接受。输出语言属于 `CourseGenerationJob` 的不可变输入，而不是 Web 临时状态或按标题推断；重试沿用原任务语言，历史任务迁移为 `zh-CN`。

日期：2026-07-15

## 1. 决策摘要

Lesson Writer 从单次“检索后提交整篇 JSON”改为 product orchestrator 控制的 coverage、evidence、unit composition、verification 和 atomic submission 流水线。Lesson Writer 拥有独立预算配置与累计计量，不再与 Course Architect 或单轮问答共用 1,500 token 输出上限。

这是一条单角色、有限阶段的工作流，不是自主多 Agent。Postgres job/run/tool trace 继续拥有状态与成本事实，Redis 只负责投递。

## 2. 背景

当前实现最多执行 3 次 Lesson evidence search，将不超过约 12,000 estimated tokens 的 evidence 放入一次 provider 请求，并以 1,500 output tokens 提交整份 `LessonDraftArtifact`。Schema 只要求至少一个 block，因此“很短但引用有效”的简介能够成功，无法代表学习内容已经完整覆盖课节目标。

仅提高单次 `max_tokens` 会增加长度，却不能解决覆盖遗漏、重复扩写、跨大 JSON 截断和失败后部分提交问题。

## 3. 决策

- coverage plan 是本 attempt 的受控临时 artifact，列出最多 8 个覆盖单元；它不是持久化课程事实。
- evidence 仍只来自当前 workspace、Course Version source snapshot 和 Lesson objective 限定的产品检索。
- 每个 unit writer 只读取必要 evidence IDs；history、其他 unit 输出和模型自述不能签发新 citation。
- verifier 只判断 coverage/schema/citation/重复，不拥有检索、发布或扩大范围权限。
- 最终 Lesson Draft 在所有 unit 和 verifier 通过后一次性事务提交；中间结果只能存在于受限 runtime/trace，不成为 Reader 内容。
- 独立默认预算为 48k evidence、8k 单调用输出、32k attempt 累计输出、12 次 provider 调用和 20 分钟墙钟；均可配置但不能由模型修改。
- provider 返回 `finish_reason=length`、累计计量越界或 wall-clock 到期视为失败，禁止尝试解析截断 JSON 后静默提交。
- worker 在长 attempt 中续租并检查取消；失去 lease 后即使 provider 返回成功也不得持久化。

## 4. 成本事实

每个 provider call 写入 tool/phase、ordinal、状态、延迟、input tokens 和 output tokens；AgentRun 保存 attempt 累计值。无法从 provider 获得精确 usage 时不得伪造金额，记录缺失并使用本地估算执行硬预算。

价格不是数据库事实合同。UI 或报告需要金额时，应以实际 tokens 与当时配置的费率快照计算；切换 provider/model 不改变权限、引用和失败边界。

## 5. 影响

- 正常课节可以跨多次调用生成，比当前 1,500-token 简介显著完整。
- 成本和延迟会随 coverage 单元增长，但有 attempt 级硬护栏且可审计。
- 需要扩展 prompt/artifact、orchestrator、settings、trace、heartbeat、fake provider tests 和 Web 错误映射。
- 不要求新增 Lesson 中间内容表；只有成功的最终 `lesson_versions`/`lesson_citations` 是正式内容事实。
- 现有 Lesson Version 模型已经允许多份 draft；重生成只需创建新 job/version，Web 不得因发现一份 draft 就隐藏重生成入口。专注内容页是读取同一版本事实的表现层，不复制正文或创建新的发布状态。

## 6. 未采用方案

### 只把单次输出改为 8k 或更高

拒绝。它仍把覆盖规划、写作和校验压在一次调用中，长 JSON 更容易截断，也无法判断遗漏。

### 无技术上限持续生成

拒绝。self-host 部署必须能限制成本、租约和异常来源放大；无限运行也无法提供稳定取消和重试语义。

### 多个自主 Writer Agent 并行协作

拒绝。当前没有委派、共享事实、冲突合并或部分成功合同；product orchestrator 的确定性 unit 调度已经足够。

## 7. 生效 Gate

本 ADR 与 Spec 004 已于 2026-07-15 获人工接受并生效。实现若改变 48k/32k/12 calls/20 minutes 中任一量级或引入并行 provider 调用，必须重新评审成本与 worker 并发。

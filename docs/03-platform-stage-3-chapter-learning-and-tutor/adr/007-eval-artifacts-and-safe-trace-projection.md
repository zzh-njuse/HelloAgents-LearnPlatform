# ADR 007：Eval 产物与安全运行视图的归属

状态：已接受（2026-07-16 人工 Gate）

日期：2026-07-15

## 1. 决策摘要

Stage 3 的可重复质量门禁采用“版本库拥有 eval 定义，本地 artifact 保存单次报告”的方式；产品运行诊断继续以 Postgres 中现有 AgentRun/AgentToolCall 为事实来源，通过显式白名单投影提供只读 API，不复制为第二套 trace，也不公开运行内容。

Slice 3 不新增 eval 数据库表，不持久化 prompt/evidence/raw provider response，不计算货币金额。真实 provider eval 是显式、预算受控的观察命令，默认测试路径保持离线。

## 2. 背景

当前 Course Architect、Lesson Writer 和 Tutor 已记录角色、attempt、状态、step、token、时间、tool 名称、结果数、延迟和安全错误码，但没有产品 API/Web 读取这些信息。与此同时，现有 fake-provider tests 验证大量功能合同，却没有统一的 eval case 清单、机器可读报告和真实 provider 基线。

若直接暴露 ORM 或日志，会泄露 prompt、问题、证据、原文、provider 配置或内部连接信息。若为 eval 建立产品表和仪表盘，则会在尚未证明长期需求前引入 schema、保留、删除和权限负担。若直接把 token 按当前单价换算金额，又会把不断变化的费率误写成历史事实。

## 3. 决策

### 3.1 运行事实只保留一份

- AgentRun/AgentToolCall 继续是受控 Agent 运行和阶段调用的权威事实。
- API 使用专用 response schema 按字段白名单投影，不直接序列化 ORM，不提供通用 log/blob 字段。
- Workspace 是查询的第一边界；Course、Tutor Session/Turn 只用于筛选和生成可读身份。
- API 可以从时间戳派生 duration，但不得推断缺失的 provider usage、调用或金额。
- 通用运行摘要暂不展示 provider/model，避免 Course 与 Tutor 现有快照粒度不一致造成误导；Stage 5 若需要统一成本治理，再定义不可变 provider/model/rate snapshot。

### 3.2 Eval 定义属于代码，单次报告不是产品事实

- fixture manifest、case schema、evaluator、硬门禁和报告 schema 与代码一起版本化。
- 生成报告包含代码版本、case 版本、运行模式和指标，写入被 Git 忽略的 artifact 目录。
- 只有人工整理的阶段基线摘要进入 Stage review/summary 文档。
- Slice 3 不创建 eval_runs、eval_cases 或 eval_scores 等产品表；若未来需要跨版本趋势、多用户对比或 UI 管理，再单独立 ADR。

### 3.3 确定性与非确定性评估分离

- 默认 eval 使用 fake provider，验证 schema、引用归属、scope 隔离、原子提交、拒答、取消、预算和语言等确定性合同。
- coverage、重复率和 citation 覆盖可由确定性 evaluator 计算，但阈值在积累基线前仅作为观察。
- 教学清晰度、相关性和完整度允许人工 rubric；不得在 Slice 3 通过另一个模型的单次评分形成硬门禁。
- 真实 provider 模式必须显式开启、设置预算并在调用前确认外发边界；不得被 pytest、Compose 启动或 CI 隐式触发。

### 3.4 数据最小化

运行摘要只允许：业务身份、role、status、attempt、step_count、token usage、时间、duration、安全错误码，以及 tool name/ordinal/status/result_count/latency。

禁止：prompt、消息、问题、回答、草稿、coverage/evidence、chunk、原文、文件路径、tool input/input hash、provider key/Base URL、连接串、环境变量、任意日志和 raw response。

## 4. 删除与保留

- Workspace 删除继续按 ADR 005 清理关联 run/tool trace；运行摘要 API 不改变删除权威和顺序。
- Course 或 Tutor 业务对象不可回读时，视图不复活内容，只返回安全类型与“已删除”身份。
- 本地 eval artifact 不属于产品数据库事实，由开发者按工作区清理；其中仍不得写入本 ADR 禁止的敏感字段。

## 5. 影响

- 优点：复用现有事实来源、无 migration、泄露面小、默认零外部调用、质量回归可以稳定重复。
- 代价：Slice 3 不提供长期趋势、金额账单、完整 provider 维度或 raw 调试体验；真实模型质量仍需统计基线和人工判断。
- Web/API 必须维护安全 response schema 与负面测试，新增 trace 字段不会自动对外公开。
- Stage 5 若引入成本仪表盘，需要另行决定 provider/model/rate snapshot、币种、价格版本和保留策略。

## 6. 未采用方案

### 将所有 eval 结果写入 Postgres 并建设仪表盘

拒绝。当前需求是阶段质量门禁，不是多用户 eval 产品；会提前引入 schema、删除、权限和保留复杂度。

### 直接公开内部 trace 或 worker 日志

拒绝。日志与内部模型包含敏感内容和配置，且不是稳定 API 合同。

### 按当前模型价格实时显示金额

拒绝。缺少统一的不可变 provider/model/rate snapshot，当前换算会把估算伪装为历史事实。

### 默认调用真实 provider 做 CI Gate

拒绝。它具有外发、费用、速率限制和非确定性，不能成为默认测试路径。

### 使用 LLM-as-judge 作为唯一质量门禁

拒绝。评分模型同样会漂移且增加费用；Slice 3 先以确定性合同和人工 rubric 建立基线。

## 7. 生效 Gate

本 ADR 与 Spec 005 必须同时经人工接受才生效。任何以下变化都需要重新评审：新增 eval 产品表、保存 raw prompt/evidence/response、默认外部 provider eval、对外展示货币金额、公开 provider 配置，或让运行摘要跨越 Workspace 边界。

本 ADR 与 Spec 005 已于 2026-07-16 获人工接受并生效。

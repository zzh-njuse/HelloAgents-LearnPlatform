# Spec 005：可重复质量门禁与安全运行摘要

状态：已接受（2026-07-16 人工 Gate）

日期：2026-07-15

适用阶段：Platform Stage 3 Slice 3

## 1. 评审结论摘要

Slice 3 建议作为 Stage 3 的收尾切片，不提前进入练习、掌握度、长期 Memory、Skill、MCP 或自主多 Agent。

本切片解决两个已经存在但尚未闭环的问题：第一，Course Architect、Lesson Writer 和 Tutor 的正确性目前主要由功能测试与单次人工观感保证，缺少可重复的质量回归；第二，系统已经记录 run/tool trace，但用户只能看到任务状态，无法安全地了解一次运行做了什么、消耗多少 token、失败在哪个阶段。

本切片不建设完整运维平台，也不把可变价格写成产品事实。质量用版本化 eval case 和可复现报告约束；运行诊断只公开白名单元数据，不公开 prompt、问题正文、回答正文、证据、上传原文、provider 配置、内部 URL 或绝对路径。

### 1.1 Stage 3 原始目标核对

本 Spec 所称“收尾切片”不表示 Stage 3 在 Slice 2 后已经全部完成，而是表示剩余工作只用于关闭原有质量 Gate 和交付记录，不再增加新的学习能力。

| 路线图原始范围或完成 Gate | 当前事实 | Slice 3 结论 |
|---|---|---|
| course/section/lesson/version/citation | Slice 1 已建立 Postgres 模型、来源快照、发布、激活、重生成和引用回读 | 已完成，不重做 |
| Course Architect 与 Lesson Writer 受控生成 | Slice 1/2 已实现有界 step/search、预算、取消、重试、coverage pipeline 和原子提交 | 已完成，不扩权 |
| Course Reader 三栏核心体验 | 已实现课程结构、正文、引用、Tutor、紧凑预览和专注阅读；2026-07-15 Chrome smoke 已接受 | 已完成，Slice 3 只防回归 |
| Tutor 绑定 workspace、section/lesson、citation 和最小 context | 已实现 Course Version 固定、lesson/course scope、短期 Session history、证据 ledger、拒答、取消和重试 | 已完成；短期 context 不升级为长期 Memory |
| 最小 run/tool trace | AgentRun/AgentToolCall 已在 Course 与 Tutor 路径持久化，并随 Workspace/Tutor 删除清理 | 记录事实已完成；安全运行摘要只是现有事实的只读产品化，不是新 runtime |
| 生成内容发布与重生成 | Course Version、Lesson Version、发布、激活、历史草稿和独立 Course 对比已实现 | 已完成，不改变语义 |
| 章节内容可追溯、可版本化 | API tests、引用回读与人工 smoke 已覆盖 | 已完成 |
| Tutor 资料不足时不伪造引用 | artifact 校验、未知 citation 拒绝、事实 block 必须引用 evidence ledger 已有测试 | 已完成，进入固定 eval 防回归 |
| Course Reader 支持稳定重复学习操作 | 课程切换、课节切换、Reader、Tutor scope/history 和长文阅读已通过人工 Chrome smoke | 已完成；Edge 完整矩阵不是原完成 Gate |
| RAG/citation/lesson 最小 eval；固定 eval case 可重复运行 | 现有 focused tests 已覆盖部分确定性合同，但尚无统一的固定样本清单、eval runner、指标报告和真实 provider 观察基线 | **未完成，是 Slice 3 必须关闭的原始 Gate** |

因此，只有 Spec 005 的固定 eval case 与交付复验完成后，才可以在 Stage 3 总结中声明全部预设完成 Gate 已关闭。脱敏运行摘要用于兑现蓝图中开发者 trace 与普通学习界面分离的原则，并让已经存在的最小 trace 可被安全诊断；若其实现影响 eval 收尾，不得以扩大仪表盘范围挤占固定 eval Gate。

## 2. Goal / Context / Constraints / Done when

| 项目 | 内容 |
|---|---|
| Goal | 为现有 Course/Tutor 能力建立可重复质量门禁，并让用户在不泄露内容和配置的前提下查看运行状态、阶段、token、耗时和错误 |
| Context | Postgres 已保存 AgentRun/AgentToolCall；现有测试以 fake provider 功能路径为主；真实 provider 质量仍依赖人工 smoke |
| Constraints | 默认 eval 不发起外部模型调用；不保存或展示敏感内容；不伪造金额；不复制运行事实；不引入 Stage 4 能力 |
| Done when | 固定 eval case、确定性门禁、可选真实 provider 观察、脱敏运行摘要 API/Web、focused tests、Compose smoke 和 Stage 3 总结全部完成 |

## 3. 用户路径

### 3.1 运行记录入口

- Workspace 提供独立的“运行记录”入口，不把诊断信息塞进 Reader 正文或 Tutor 对话流。
- 默认显示最近运行，支持按 Course、角色和状态筛选。
- 每条记录至少显示：任务身份、角色、状态、attempt、step 数、输入/输出 token、开始时间、耗时和安全错误说明。
- 展开记录后按顺序显示阶段或工具名、状态、结果数量、耗时和安全错误码。
- Course 生成任务与 Tutor turn 应显示可识别的业务身份，例如 Course 标题、课节标题或 Tutor 范围；不能只显示内部 UUID。
- 页面是只读诊断入口。重试、取消和删除继续由现有任务或业务页面负责。

### 3.2 安全展示边界

运行记录不得返回或渲染：

- system/user prompt、问题正文、回答正文、生成草稿、coverage plan 或模型原始响应；
- evidence、chunk 文本、上传原文、文件绝对路径；
- API key、provider Base URL、内部域名、连接串、环境变量或日志；
- tool input、input hash 或可能被用于关联敏感输入的调试字段。

Slice 3 只展示 token、调用次数、阶段耗时和结果数量，不展示货币金额。价格、币种、折扣和套餐额度属于可变运营配置，留到 Stage 5 的成本治理处理。

## 4. 可重复 eval 合同

### 4.1 两种运行模式

1. **离线确定性模式**：默认模式，使用版本库内公开或脱敏 fixture 与 fake provider，不访问外部模型，可进入本地回归和 CI。
2. **真实 provider 观察模式**：必须显式选择 provider、确认会外发脱敏输入并设置运行预算；不得由普通测试、启动命令或 CI 自动触发。

真实 provider 结果用于发现质量漂移和人工验收，不因单次非确定性分数直接阻断提交。只有经过多轮基线确认、阈值稳定且人工 Gate 接受后，某一指标才可升级为硬门禁。

### 4.2 固定样本矩阵

| 能力 | 最低样本 |
|---|---|
| Course Architect | 单来源、多来源、来源冲突、证据不足、中文、英文、失效 citation、预算耗尽 |
| Lesson Writer | 简单课节、多 coverage unit、重复证据、覆盖缺口、结构修复、未知 citation、截断、取消、中文、英文 |
| Tutor | lesson scope、course scope、无证据拒答、跨 scope 隔离、历史隔离、失效 citation、取消、重试、提示注入样本 |

fixture 只使用公开、项目自有或不可逆脱敏内容，不包含用户上传原文、生产 prompt、私有连接信息和 provider key。

### 4.3 硬门禁与观察指标

以下项目在离线模式中是硬门禁：

- artifact/schema 校验通过率 100%；
- citation 必须来自当前 workspace 和固定 source snapshot，通过率 100%；
- Course/Lesson/Tutor scope 隔离通过率 100%；
- 取消、超时、预算耗尽或校验失败时不提交晚到结果或半成品，通过率 100%；
- 无足够证据时按合同拒答或明确 limitation，通过率 100%；
- 请求语言、任务语言和重试语言保持一致，通过率 100%。

以下项目先作为观察指标，不在 Slice 3 设定普适硬阈值：

- 课程/课节 coverage、事实 citation 覆盖、重复率；
- 回答相关性、教学清晰度、内容完整度；
- input/output token、provider 调用数、耗时和失败分布。

观察报告必须保留样本版本、代码版本、运行模式、provider/model（若使用）、配置摘要和指标；不得包含原始敏感内容。

## 5. API 合同

建议增加只读接口：

- `GET /api/v1/workspaces/{workspace_id}/agent-runs`
- `GET /api/v1/workspaces/{workspace_id}/agent-runs/{run_id}`

列表支持受限的 `course_id`、`role`、`status` 和 `limit` 过滤，默认按最新开始时间倒序，单次最多 50 条。详情只返回第 3.2 节允许的白名单字段与有序 tool calls。

所有查询必须先约束 `workspace_id`。不存在或不属于当前 Workspace 的 run 返回 404；非法过滤条件返回 422。接口不得直接序列化 ORM 模型，也不得提供任意日志下载。

## 6. Eval 输出与保留

- eval case、确定性 evaluator 和基线定义进入版本库。
- 每次生成的报告写入 gitignore 覆盖的本地 artifact 目录，默认不写 Postgres、不提交 Git。
- 阶段收尾只提交经过人工整理的摘要、命令、样本版本、指标和结论，不提交包含模型原文的大型 raw report。
- Slice 3 不新增 eval case/result 数据库表，不建设历史趋势仪表盘。

## 7. 失败行为

| 场景 | 行为 |
|---|---|
| trace 读取失败 | 不影响课程阅读、生成和 Tutor；运行记录显示可重试的读取错误 |
| 运行仍在进行 | 显示当前状态与已提交阶段，不推断尚未发生的 token 或耗时 |
| usage 缺失 | 显示“未报告”，不得用估算值冒充 provider 实际 usage |
| 运行关联对象已删除 | 保留安全的运行类型和时间；业务标题显示“已删除”，不回读已删内容 |
| eval fixture 或报告 schema 无效 | eval 命令失败且不覆盖上一次人工接受的基线摘要 |
| 真实 provider 未确认或未配置 | 在调用前失败，不回退为隐式外部请求 |

## 8. 明确不做

- 练习、作答、评分、掌握度、错题和复习队列；
- 长期 Memory、学习画像、Skill、MCP、自主多 Agent；
- 金额账单、套餐余额、费用预测或完整运维仪表盘；
- prompt/evidence/raw response 查看器或日志下载；
- 旧资料页码猜测、静默重解析或改写 Course source snapshot；
- Edge/移动端完整兼容矩阵。Slice 3 只保证现有 Chrome 基线不回归；跨浏览器验收另立范围。

## 9. 验证

- API：workspace 隔离、过滤上限、已删除关联、unsafe field 缺失、tool call 顺序和 404/422。
- Eval：三种角色全部覆盖成功、拒答、取消、预算、无效 citation、scope 隔离和语言一致性。
- Web：运行记录筛选、任务身份、进行中状态、失败详情、空状态和窄 viewport 无重叠。
- 安全自审：响应 schema 与浏览器网络响应均不含第 3.2 节禁止字段。
- 回归：API focused tests、migration head、Web lint/build、Compose ready/Web 200 和 Course/Tutor 业务 smoke。
- 真实 provider：只有人工明确批准后才运行一组公开/脱敏样本，并将其标记为观察结果而非确定性通过证明。

## 10. 待人工 Gate

1. Slice 3 是 Stage 3 的收尾切片，只做 eval、脱敏运行摘要和交付闭环。
2. 用户可查看 token、调用数、耗时、阶段和错误，但不查看 prompt、内容、证据、配置、日志或货币金额。
3. 运行记录是 Workspace 级独立入口，默认最近记录，可按 Course/角色/状态筛选。
4. 离线 fake-provider eval 是硬门禁；真实 provider eval 必须显式确认，当前只作观察。
5. eval case/evaluator 进入版本库，raw report 默认留在被忽略的本地 artifact，不新增 eval 数据库表。
6. coverage、citation 覆盖、重复率、教学清晰度和内容完整度先记录基线，不在本切片武断设置普适阈值。
7. 旧资料重解析、金额成本、完整运维台和跨浏览器矩阵不属于本切片。

以上 Gate 已于 2026-07-16 获人工接受。实现必须把固定 eval 作为不可降级的完成 Gate，并以脱敏运行摘要和交付复验收尾；不得借实现任务包改变本 Spec。

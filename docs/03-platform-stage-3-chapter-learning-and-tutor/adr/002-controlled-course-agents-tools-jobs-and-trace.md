# ADR 002：受控课程 Agent、工具、任务与最小审计轨迹

状态：已接受（2026-07-14 人工 Gate）
日期：2026-07-13
适用阶段：Platform Stage 3 Slice 1

## 1. 决策摘要

Stage 3 Slice 1 引入两个有界领域角色：Course Architect 生成课程大纲，Lesson Writer 生成单个课节。它们在 `academic_companion` 中实现轻量 adapter，复用 `hello_agents` 的 Agent/runtime/tool 基础，但不直接复用现有原型 `LearningAgent`。

Product app 拥有编排、workspace/source scope、Postgres job、Redis 投递、provider 配置、工具实现、artifact 校验、重试/取消和最终事务提交。Agent 不直接访问 ORM、Redis、文件系统或任意网络，只能使用产品注入的 `CourseEvidenceSearch` 与对应结构化提交工具。

两个角色不自由对话，也不自主委派。它们通过已校验并持久化的 Course Version/Lesson artifact 交接。每次 job attempt 使用全新 runtime，并同时记录最小 `agent_run` 和 `agent_tool_call` 轨迹；不保存原始 prompt、资料正文、原始检索 query 或 provider 原始响应。

## 2. 背景与资产判断

现有 `academic_companion.agents.LearningAgent` 绑定内置 CS/LeetCode RAG、本地 UserModel/Memory、TodoWrite、原型章节字典和 session 语义。直接复用会绕过 workspace、精确来源版本、Stage 2 citation、Postgres job 和删除合同，因此只能作为交互与工具封装的参考。

可复用资产包括：

- `hello_agents` 的 Agent 生命周期、工具调用和 trace 基础；
- `academic_companion` 研究 pipeline 的结构化上下文/artifact 交接思路；
- Stage 2 的 generation provider、受引用回答、证据回读、RQ worker、lease/retry/cancel 和资源预算模式。

不能复用的原型事实包括本地 JSON memory、内置资料 schema、隐式 session、静默降级和对 prototype API/Web 的依赖。

## 3. 决策驱动因素

1. 展示真实 Agent 的检索、判断和结构化产出能力，而不是把一次 LLM 调用改名为 Agent。
2. Agent 不得扩大 workspace、source snapshot 或工具权限。
3. provider 失败、输出无效、取消和重复投递必须服从产品任务合同。
4. 成本可预测：用户逐次触发、步数有限、检索有限、无自动全课程生成。
5. 第一批 Agent 需要可审计，但不能因 trace 保存敏感资料或制造第二事实来源。
6. 后续 Tutor、Skill、MCP 和多 Agent 可以建立在稳定合同上，而不是现在一次性造通用平台。

## 4. 模块与依赖边界

### `hello_agents`

- 提供通用 Agent/runtime/tool/trace 协议。
- 不认识 workspace、Course、document version、Postgres ORM 或产品 settings。
- Slice 1 不为课程需求反向加入产品特例。

### `academic_companion`

- 提供 Course Architect 和 Lesson Writer 的领域 prompt、结构化 artifact 类型及 runtime adapter。
- 接收已经绑定权限的工具对象和本次运行上下文。
- 不 import `apps`，不直接打开数据库连接，不决定发布、激活、重试或删除。

这里的 adapter 不是再造一个产品服务，也不是把现有 `LearningAgent` 改个名字。它是一层窄接口，负责把产品提供的不可变输入和已绑定工具装配成 `hello_agents` 可以运行的 Agent，并把运行结果转成领域 artifact 候选：

1. `apps/api` 从 Postgres 读取 job、workspace、Course、精确 source snapshot 和预算，先完成权限与状态校验。
2. `apps/api` 创建只对本次 job 有效的 `CourseEvidenceSearch`/`Submit...` 工具对象；workspace 和 source IDs 封装在对象内部，不作为模型可改参数。
3. `academic_companion` adapter 接收普通 DTO、工具协议和 runtime 配置，构造 Course Architect 或 Lesson Writer 的 prompt、输出 schema 和工具白名单。
4. adapter 调用 `hello_agents` 的通用 runtime 执行决策/工具循环，返回结构化 artifact 候选、终止原因和最小运行事件。
5. `apps/api` 再做 citation、预算、租约和状态校验，并在 Postgres 事务中提交版本；adapter 自己无权发布课程或写数据库。

概念调用关系如下，具体类型名可在实现时遵循仓库现有 Python 风格：

```text
apps/api product orchestrator
  -> 构造 ProductBoundCourseTools(workspace_id, source_snapshot, lesson_scope)
  -> academic_companion.run_course_architect(request_dto, bound_tools, runtime_config)
       -> hello_agents Agent/runtime
       -> 只看见 CourseEvidenceSearch + SubmitCourseOutline
  <- 返回 CourseOutlineArtifactCandidate + run events
  -> apps/api 权威校验并事务提交 Postgres
```

这样复用的是 `hello_agents` 的通用运行循环、消息/工具协议、停止条件和 trace hook；`academic_companion` 拥有教学领域角色及 artifact schema；`apps` 仍拥有产品事实与权限。

### `apps/api`

- 拥有 API、ORM、job、provider、队列、workspace/source 校验和最终 artifact 持久化。
- 构造 product-owned tools，并以闭包或不可变上下文固定 workspace、Course Version、Lesson 和 source snapshot。
- 验证 Agent 输出和 citation，决定成功/失败及错误码。

依赖保持 `apps -> academic_companion -> hello_agents`；不得用 callback 反向 import 产品模块来规避该方向。

## 5. 角色与交接

### 5.1 Course Architect

输入是课程标题、目标、可选受众和精确来源快照。它可以检索证据并提交一个结构化大纲，不能生成完整课节、发布课程或调用 Lesson Writer。

允许工具：

- `CourseEvidenceSearch`
- `SubmitCourseOutline`

### 5.2 Lesson Writer

输入是已持久化 Course Version 的结构摘要、目标 Lesson 的标题/目标和同一来源快照。它可以检索证据并提交一个结构化课节草稿，不能修改大纲、来源集合或发布状态。

允许工具：

- `CourseEvidenceSearch`
- `SubmitLessonDraft`

### 5.3 交接方式

Course Architect 成功后，服务端校验并事务性创建 Course Version、Section 和 Lesson 槽位。Lesson Writer 只读取该持久化 artifact。两者之间不存在共享聊天历史、隐藏 scratchpad 或进程内对象依赖。

这是一条由 product orchestrator 控制的多角色流水线，不宣称为自主多 Agent 协作。未来若引入委派、并行角色或协调 Agent，必须另写 Spec/ADR。

### 5.4 简短运行示例

假设用户选择 12 份搜索推荐资料，希望生成“搜索与推荐系统入门”课程。

Course Architect 的一次成功运行可以是：

| Step | Agent 决策 | 工具调用 | 产品侧约束与结果 |
|---|---|---|---|
| 1 | 先确定课程的基础链路 | `CourseEvidenceSearch("召回、排序与系统链路")` | 服务端只在这 12 份精确资料版本内返回最多 5 条 evidence |
| 2 | 补足评估与实验部分 | `CourseEvidenceSearch("离线评估、在线实验与指标")` | 再返回最多 5 条，不允许搜索网页或其他 workspace |
| 3 | 检查工程实践覆盖 | `CourseEvidenceSearch("特征、服务与监控")` | 返回最多 5 条，并继续服从总 evidence 预算 |
| 4 | 补足尚未覆盖的主题 | `CourseEvidenceSearch("数据闭环与常见失败模式")` | 这是典型运行的最后一次检索，仍保留提交和修复空间 |
| 5 | 根据已有证据组织课程 | `SubmitCourseOutline({...})` | 提交 10 个 Section、每节 1 至 3 个 Lesson，引用只能使用本次运行签发的 evidence IDs |
| 6 | 仅当第五步 schema/citation 无效 | `SubmitCourseOutline({...修复后...})` | 服务端返回结构化校验错误后允许一次修复；有效则结束，不能再检索 |

Lesson Writer 随后为其中“为什么需要召回”这个 Lesson 单独运行：

| Step | Agent 决策 | 工具调用 | 产品侧约束与结果 |
|---|---|---|---|
| 1 | 查找核心概念 | `CourseEvidenceSearch("为什么全量排序不可行，召回的目标是什么")` | 限定同一 Course Version snapshot 和当前 Lesson objective |
| 2 | 补充实例和边界 | `CourseEvidenceSearch("候选集规模、覆盖率与效率示例")` | 返回最多 5 条新 evidence |
| 3 | 形成课节草稿 | `SubmitLessonDraft({...})` | 每个事实 block 引用当前 run 的 evidence ID |
| 4 | 仅在结构化校验失败时修复 | `SubmitLessonDraft({...修复后...})` | 成功后创建 draft Lesson Version；Agent 无权发布 |

Course Architect 若用满 5 次检索，则第六步必须用于提交，没有修复回合；典型使用 3 至 4 次检索，为提交和一次修复保留空间。Lesson Writer 若用满 3 次检索，则第四步必须用于提交；只用 2 次检索时可保留一次修复。所谓“只允许产品证据工具和结构化提交工具”，具体意味着 Agent 看不到数据库、文件系统、网页、MCP、Memory、TodoWrite、其他 Agent、发布接口或任意通用 RAG 工具。

## 6. 工具合同

### 6.1 `CourseEvidenceSearch`

Agent 可提供简短语义 query，但不能提供 workspace ID、document ID、version ID 或任意过滤表达式。服务端强制覆盖以下 scope：

- 当前 job 的 workspace；
- 当前 Course Version 的精确 source snapshot；
- Lesson Writer 额外绑定目标 Lesson objective；
- 仅 Stage 2 已授权且仍可回读的 chunk。

工具沿用 Stage 2 的 Qdrant 候选召回和 Postgres 权威回读。默认每次最多返回 5 条合格 evidence；Course Architect 每个 attempt 最多调用 5 次，Lesson Writer 最多调用 3 次，总证据输入预算均默认约 12,000 estimated tokens。证据不足时返回结构化不足原因，不能为了凑满数量放宽来源或相关性门槛。

工具返回短期 evidence ID、最小必要文本和可展示来源摘要。短期 ID 仅在当前 attempt 有效，最终持久化 citation 时由服务端解析；模型提供的 document/chunk 主键一律不可信。

### 6.2 结构化提交工具

每个角色只能调用对应提交工具。提交后 runtime 结束，不允许继续搜索或第二次提交。

服务端验证：

- schema、类型、长度、数量和顺序；
- evidence ID 存在且属于当前 attempt；
- citation 覆盖满足 Spec；
- 输出不含未知 block、重复 key 或越界内容。

首次提交无效时，orchestrator 可以在同一 attempt 的剩余预算内给出结构化错误并允许一次修复提交；第二次仍无效则以 `invalid_agent_artifact` 失败。修复不得获得新工具或放宽 citation 规则。

## 7. Runtime 与预算

- 每个 job attempt 创建全新 runtime，不加载 prototype session 或长期 Memory。
- Course Architect 最多 6 个 Agent 决策 step、5 次 evidence search；Lesson Writer 最多 4 个决策 step、3 次 evidence search。每个角色均有 1 次初始提交和最多 1 次修复提交；搜索和提交都消耗 step，因此用满检索额度后将没有修复余量。
- 达到 step、tool、evidence、输出 token 或墙钟预算立即失败，不自动换模型或转为无引用生成。
- 取消请求在 provider 调用前后、工具调用前后和最终提交前检查；provider 无法中断时，返回后仍不得提交已取消结果。
- 资料内容按不可信 evidence 包裹，明确禁止其改变系统规则、工具权限、输出 schema 或来源 scope。
- runtime 不提供文件系统、shell、MCP、网页、TodoWrite、Memory 或任意 Agent 调用工具。

具体超时和输出 token 默认值在实现前根据当前 DeepSeek Flash 实测写入配置和测试；改变上限不改变上述权限边界。

## 8. Provider 与外部处理

- 复用 Stage 2 已有 `PRODUCT_GENERATION_PROVIDER`、`PRODUCT_GENERATION_MODEL`、base URL 和 key 配置作为共享连接基线。
- 默认 provider/model 继续使用已确认的 DeepSeek Flash；Course Architect 和 Lesson Writer 可增加独立模型名、温度、输出 token、超时和预算覆盖配置。
- 角色配置未设置时可继承共享 generation 配置；调用失败不切换 provider/model，也不降级为本地或无引用模式。
- 每次新建大纲或课节 job 都要求 API 请求携带 `external_processing_ack=true`。重试沿用原 job 已记录的确认和同一来源快照，不扩大处理范围。
- Web 在每次新 job 前显示 provider、来源数量和资料片段将被外发的事实；只在第一次创建 Course 时确认并不代表对后续新 job 永久授权。
- 不向 provider 发送 API key、内部 URL、绝对路径、无关 workspace 数据或完整文件；只发送任务必要的目标、结构摘要和预算内 evidence。

## 9. 任务与队列

`course_generation_jobs` 是权威状态；Redis/RQ 只传递 `job_id` 和 attempt 标识。大纲和课节可共用受控 generation worker/queue，但必须与 ingestion 的 job 类型、超时和并发预算明确隔离。

每个 attempt 遵循：

1. 原子 claim Postgres job，并取得 lease；
2. 校验 Course、workspace、source snapshot、外部处理确认和取消状态；
3. 建立 `agent_run`，构造权限已绑定的工具和全新 runtime；
4. 执行 Agent，持续 heartbeat，并在边界检查取消/租约；
5. 校验 artifact；
6. 在仍拥有 lease 时，事务性写入版本/citation、结束 run 并标记 job 成功；
7. 对 retryable 错误进入 `retry_wait`，对确定性合同错误直接失败。

队列投递失败由 reconciler 根据 Postgres queued/retry 状态恢复。重复消息、超时 worker 和迟到 provider 响应不得产生重复版本。

## 10. 最小审计轨迹

Slice 1 随首个 Agent 落地最小事实表，推荐独立于 Stage 2 answer trace：

### `agent_runs`

至少保存：`id`、`workspace_id`、`job_id`、`attempt`、`role`、runtime/prompt schema version、provider/model、状态、开始/结束时间、步数、输入/输出 token 统计、总延迟、终止原因和错误码。

### `agent_tool_calls`

至少保存：`id`、`agent_run_id`、顺序、工具名、参数摘要 hash/数量、结果摘要 hash/数量、状态、延迟、错误码和时间。

明确不保存：

- 原始 system/user prompt 或隐藏推理；
- 原始检索 query；
- evidence 正文、课程正文或 provider 原始响应；
- API key、内部连接 URL 和绝对路径。

正式课程内容和 citation 继续由课程表拥有；trace 只解释运行过程，不成为内容事实来源。Slice 1 提供内部查询和测试能力即可，完整 dashboard、成本治理与保留策略 UI 留到 Stage 5。

## 11. 错误、重试与取消

- provider timeout/暂时不可用、queue 投递失败可在 attempt 上限内重试。
- source snapshot 失效、证据不足、权限失败和预算超限默认是确定性失败；需要用户改变输入或新建 job。
- artifact 首次无效允许一次受控修复，仍无效则失败；不能无限自我修正。
- 重试复用原 job 目标和来源快照，并创建新的 Agent Run；不得覆盖之前 run 记录。
- 用户取消只停止尚未提交的工作；已成功事务提交的 Course/Lesson Version 不回滚。
- worker 丢失 lease 时结束本地执行并记录终止原因，不能提交迟到 artifact。

## 12. 安全边界

- 产品代码在工具构造时固定授权范围，模型参数不能覆盖。
- evidence 是不可信输入；提示注入测试必须覆盖索要新工具、跨 workspace、泄漏 prompt、忽略 citation 和扩大来源范围。
- 对外日志和 API 只返回稳定错误码及安全摘要，不返回 provider 原始错误体或 prompt。
- provider 输入必须能由 job/source/run ID 审计到范围，但 trace 不复制敏感正文。
- 本地 self-host 单用户假设不取消 workspace 过滤和所有权检查。

## 13. 备选方案

### 方案 A：直接复用现有 `LearningAgent`

拒绝。它绑定 prototype RAG、Memory、TodoWrite 和内置资料，不满足产品 workspace/version/citation/job 合同。

### 方案 B：在 API 内直接调用 LLM 并解析 JSON

拒绝作为最终实现。它缺少受控检索工具、停止条件和 tool trace，不能验证首个产品 Agent 的基础边界。

### 方案 C：让两个 Agent 自由对话或相互调用

拒绝。交接事实不稳定，成本和停止条件难以控制，也没有 Slice 1 产品收益。

### 方案 D：给 Agent 通用数据库或 RAG 工具

拒绝。模型可能扩大 workspace/source scope，并绕过 Stage 2 权威回读。

### 方案 E：只写应用日志，不建立 Agent trace

拒绝。无法按 run/tool 解释失败、成本和越权尝试，也不能为后续 eval/governance 提供稳定输入。

### 方案 F：保存完整 prompt、query 和 evidence 方便调试

拒绝。会复制上传原文和敏感目标，扩大泄露与保留风险；使用 hash、计数、版本和错误码即可完成基础审计。

## 14. 影响

### 正向影响

- 首个 Agent 具有真实但可控的工具循环、结构化产出和审计轨迹。
- 产品合同与领域 prompt/runtime 分离，后续 Tutor 可复用边界而不复用课程专用角色。
- provider、取消、重试、成本和引用错误均有确定归属。
- 多角色协作通过持久化 artifact 可复现，不依赖隐式会话。

### 成本与限制

- 需要新 domain adapter、product tools、job worker、trace schema 和 fake runtime 测试。
- 不提供开放式 Agent 能力，演示效果会比“万能助手”克制。
- 最小 trace 不足以替代 Stage 5 的完整可观测、成本仪表盘和数据保留治理。

## 15. 验证要求

- fake Agent 覆盖工具白名单、scope 强制覆盖、step/tool/evidence/output 预算和一次修复上限。
- prompt injection fixture 覆盖跨 workspace、索要新工具、泄漏系统提示和伪造 citation。
- worker 测试覆盖重复投递、租约丢失、取消、provider timeout、retry、queue recovery 和迟到响应。
- trace 测试确认每个 attempt/run/tool 顺序一致，且日志、API、数据库审计字段不含正文、原始 query、prompt、key、URL 或绝对路径。
- 固定 eval 覆盖大纲来源覆盖、课节事实支撑、引用有效性、证据不足拒绝、token 和延迟预算。
- 真实 provider smoke 仅在人工确认后使用无敏感 fixture；较大代码 diff 在人工批准后分风险块进入 OCR gate。

## 16. 人工 Gate

接受本 ADR 表示确认：

1. Course Architect 与 Lesson Writer 是两个受控角色，在 `academic_companion` 实现 adapter，并复用 `hello_agents` runtime；不直接复用现有 `LearningAgent`。
2. Product app 拥有编排、权限、工具、任务、provider、校验和持久化。
3. 两个角色只通过 Postgres artifact 交接，不自由对话、不自主委派。
4. Course Architect 每个 attempt 最多 6 个决策 step、5 次检索；Lesson Writer 最多 4 个决策 step、3 次检索。每个角色均有一次初始提交和最多一次受控修复；所有工具调用均消耗 step，因此修复并非无条件额外回合。默认每次检索最多 5 条，总 evidence 预算约 12,000 estimated tokens。
5. 每个新生成 job 都需要外部处理确认；重试不扩大原确认范围；失败不自动 fallback。
6. 最小 `agent_runs/agent_tool_calls` 与首个 Agent 同时落地，但不保存原始 prompt、query、资料正文或 provider 响应。

### 已确认预算理由

2026-07-14 人工 Gate 确认采用非对称预算：Course Architect 使用 6 step/5 次检索，Lesson Writer 使用 4 step/3 次检索。原因是课程最多可覆盖 20 份来源和 15 个 Section，大纲角色需要比单课节角色更大的证据覆盖空间；同时检索、提交和修复仍共享 step 上限，避免把修复变成无成本的额外循环。

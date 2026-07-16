# Stage 3 Slice 3 GLM 实现任务包

状态：可执行；Spec 005 / ADR 007 已于 2026-07-16 通过人工 Gate

用途：交给配置 GLM 的 Claude Code 或同类 coding agent 顺序实现。该 Agent 负责小范围编码和自动验证；Codex 保留需求解释、跨批合同复核、真实 provider/OCR 授权、人工 smoke、阶段总结和提交决策。

## 1. 开始前必须读取

按顺序完整读取，不得只看本任务包：

1. 根 `AGENTS.md`。
2. `docs/README.md`。
3. 四份产品方向与执行文档，尤其 `docs/AGENT_COLLABORATION_PLAYBOOK.md`。
4. 本 Stage `README.md`、`SLICE_2_SUMMARY.md`、`SLICE_3_INPUTS.md`。
5. 已接受的 `specs/005-repeatable-quality-gates-and-safe-run-summaries.md`。
6. 已接受的 `adr/007-eval-artifacts-and-safe-trace-projection.md`。
7. 当前实现及相邻测试，不得从任务包猜测代码结构。

开始时运行并记录：

```powershell
git status --short --branch
git diff --stat
```

当前未提交的 Spec/ADR、索引和本任务包是 2026-07-16 人工接受后的文档成果，不得回滚、覆盖或当作未知垃圾清理。

## 2. 总目标

在不新增 migration、不改变现有生成/Tutor 语义、不触发真实 provider 的前提下：

1. 通过现有 `AgentRun` / `AgentToolCall` 提供 Workspace 隔离的脱敏只读运行摘要 API。
2. 在 Workspace 中提供与学习正文分离的“运行记录”界面。
3. 建立可重复运行的 Stage 3 固定离线 eval case、确定性 hard gate 和机器可读脱敏报告。
4. 为真实 provider 观察模式建立显式确认和预算入口，但实现期间只做 preview/拒绝路径验证，不实际调用 provider。
5. 完成自动化复验，把实现事实交回 Codex；不要自行宣称 Stage 3 完成。

## 3. 不可越界

- 不新增或修改数据库表、migration、删除顺序或权限模型。
- 不实现练习、掌握度、复习、长期 Memory、Skill、MCP 或自主多 Agent。
- 不建设金额账单、套餐余额、历史趋势或完整运维 dashboard。
- 不返回、记录或提交 prompt、问题/回答正文、草稿、coverage、evidence、chunk 原文、上传原文、文件绝对路径、tool input/input hash、日志、API key、provider Base URL、内部域名、连接串或环境变量。
- 不猜测旧资料页码，不重解析资料，不改写 Course source snapshot。
- 不添加新的默认 provider、依赖或后台服务。
- 不运行真实 provider、真实 OCR、push、merge 或破坏性 Git 命令。
- 不修改已接受 Spec/ADR 的产品决策。发现合同冲突时停止并报告，不自行改规格。

## 4. 执行方式

批次必须按 A -> B -> C -> D -> E 顺序执行。每批只修改列出的主要边界，完成后运行该批检查并报告：改动文件、行为、检查结果、剩余问题。不要在一个大 diff 中同时重构无关代码。

除非用户明确要求，任务 Agent 不提交、不 push。不要 stash 或回滚已有文档改动。

## 5. Batch A：安全运行摘要 API

### Goal

实现：

```text
GET /api/v1/workspaces/{workspace_id}/agent-runs
GET /api/v1/workspaces/{workspace_id}/agent-runs/{run_id}
```

### 建议文件边界

- 新增 `apps/api/learn_platform_api/schemas/agent_runs.py`。
- 新增 `apps/api/learn_platform_api/services/agent_runs.py`。
- 新增 `apps/api/learn_platform_api/routers/agent_runs.py`。
- 修改 `apps/api/learn_platform_api/routers/__init__.py`（仅在现有模式需要时）。
- 修改 `apps/api/learn_platform_api/main.py` 注册 router。
- 新增 `apps/api/tests/test_agent_run_api.py`。

不要修改 `db/models.py` 或 Alembic。

### API 合同

- 所有查询先约束 `workspace_id`，不存在的 Workspace 或跨 Workspace run 返回 404。
- 列表默认按 `created_at DESC`，支持 `course_id`、`role`、`status`、`limit`；`limit` 默认 20、范围 1-50，非法值 422。
- `role` 仅接受当前实际角色：`course_architect`、`lesson_writer`、`tutor`。
- status 必须使用当前 AgentRun 状态集合，不发明新状态。
- 列表不默认加载 tool calls；详情按 `ordinal ASC, created_at ASC` 返回 tool calls。
- 业务身份从现有关系派生：Course job 显示任务类型、Course 标题和可选课节标题；Tutor 显示 Course 标题、scope 和可选课节标题。关联对象不可回读时使用空 ID/“已删除”，不得复活正文。
- duration 从 `created_at/completed_at` 派生；运行中可用当前时间展示暂态耗时，但响应必须让 Web 区分进行中，且不得写回数据库。
- usage 缺失返回 `null`，不能估算。
- 使用显式 Pydantic response model，禁止 ORM 直接序列化。

允许字段只有：run id、业务身份字段、role、status、attempt、step count、input/output tokens、created/completed time、duration、error code；详情 tool call 只允许 tool name、ordinal、status、result count、latency、error code、created time。

### 必测场景

- 三种角色的列表与详情。
- Course/lesson/Tutor 的可读身份。
- workspace 隔离和未知 run 404。
- course/role/status/limit 过滤及 422。
- tool call 稳定顺序。
- running、completed、usage 缺失和已删除关联。
- JSON 键集合负面断言：禁止字段完全不存在，而不是仅为 `null`。

### Batch A 验证

```powershell
python -m pytest -q apps/api/tests/test_agent_run_api.py
python -m pytest -q apps/api/tests
git diff --check
```

## 6. Batch B：Workspace 运行记录 Web

### Goal

在 Workspace 主区域增加清晰的“学习 / 运行记录”视图切换。运行记录与 Reader/Tutor 正文分离，不做新的营销页或运维 dashboard。

### 建议文件边界

- 新增 `apps/web/src/app/AgentRunsPanel.tsx`。
- 修改 `apps/web/src/app/App.tsx`，只负责 Workspace 级入口和选择状态。
- 修改 `apps/web/src/lib/api.ts`，增加与 Batch A 完全一致的类型和请求。
- 修改 `apps/web/src/styles.css`，保持现有安静、紧凑、可扫描设计。

### 交互合同

- 使用现有 lucide `Activity` 等图标；模式切换使用 tabs/segmented control。
- 默认进入“学习”，切换 Workspace 后清理旧 Workspace 的 run 数据和详情。
- 运行记录显示任务身份、角色、状态、attempt、token、开始时间和耗时；点击一行展开阶段详情。
- 支持 Course、角色和状态筛选；有活动 run 时每 2 秒刷新，全部终态后停止轮询。
- loading、空状态、读取失败、筛选无结果和已删除对象均有清楚状态。
- 只把 `error_code` 映射为简短安全说明，不显示服务器日志或拼接内部异常。
- 不提供取消、重试、删除、raw JSON、日志下载和金额。
- 桌面与窄 viewport 不重叠；不要在卡片内再嵌套卡片。

### Batch B 验证

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
```

随后回到仓库根运行 `git diff --check`。

## 7. Batch C：固定离线 eval 与报告

### Goal

建立默认零外部调用、可重复、可机器判定的 Stage 3 eval。不要把普通全量 pytest 改名冒充 eval；固定 case manifest 必须明确列出角色、风险和预期 Gate。

### 建议结构

```text
apps/api/stage3_eval/
  __init__.py
  cases.json
  metrics.py
  report.py
  runner.py
apps/api/tests/test_stage3_eval.py
```

如相邻代码证明另一种小范围结构更合适，可以调整文件名，但必须保留独立 manifest、runner、报告 schema 和 focused tests。

在 `.gitignore` 增加精确的 `/artifacts/eval/`；不要忽略整个 `artifacts/` 或测试定义。

### 固定 case 最低集合

- Course Architect：单来源、多来源、来源冲突/证据不足、中文、英文、未知 citation、预算耗尽。
- Lesson Writer：简单课节、多 coverage unit、重复证据、覆盖缺口与受控修复、未知 citation、截断/预算失败、取消、中文、英文。
- Tutor：lesson scope、course scope、无证据拒答、跨 scope 隔离、history 隔离、未知 citation、取消、重试、提示注入不可信输入。

允许 manifest 引用已有稳定 pytest node id，并为缺失行为新增 focused case；runner 必须逐 case 执行并记录 case id，而不是只保存一段 pytest 控制台文本。不要复制大量现有 fixture。

### Hard gates

- schema/artifact 校验 100%。
- citation 属于当前 workspace/source snapshot 100%。
- Course/Lesson/Tutor scope 隔离 100%。
- 取消、超时、预算或校验失败不提交晚到结果/半成品 100%。
- 无证据拒答或 limitation 100%。
- 请求、任务、重试语言一致 100%。

任一 hard case 失败时 runner 退出非零。

### 观察指标

为脱敏结构化 artifact 提供纯确定性指标函数：coverage、事实 citation 覆盖、重复率、tokens、调用数、耗时。指标无普适阈值，不阻断本 Slice；报告中明确标记 `observational`。教学清晰度、相关性和完整度只保留人工 rubric 字段，不调用 LLM judge。

### 报告合同

默认命令建议为：

```powershell
python -m stage3_eval.runner --mode offline
```

默认报告写入仓库根 `artifacts/eval/`，包含 schema version、UTC 时间、Git revision（无法读取时为 null）、case manifest version、mode、每 case 状态/耗时、安全指标和总计。

报告不得包含测试 stdout/stderr 全文、prompt、问题、回答、evidence、原文、路径、provider 配置或环境变量。失败只保存 case id 和稳定错误类别；详细 traceback 只留在当前终端。

### Batch C 验证

```powershell
python -m pytest -q apps/api/tests/test_stage3_eval.py
cd apps/api
python -m stage3_eval.runner --mode offline
cd ../..
python -m pytest -q apps/api/tests
git status --short
git diff --check
```

确认生成报告被 Git 忽略，case manifest 和 evaluator 正常被 Git 追踪。

## 8. Batch D：真实 provider 模式的关闭默认与 preview

### Goal

为以后人工批准的真实 provider 观察提供显式入口，但本任务只验证“不会误调用”。不得实际发送请求。

### 合同

- 非 preview 的 `--mode real` 必须同时要求类似 `--ack-external-processing`、正整数 `--max-cases` 和正整数 `--max-provider-calls`；`--preview` 不发送请求，因此不要求外发确认。
- 缺任一确认或预算时，在读取 provider key或发送请求前非零退出。
- 提供 `--preview`：只列 case id、公开/脱敏 fixture 标识、预计最大调用数和报告位置，不加载/打印 key、Base URL、prompt 或 fixture 正文。
- 普通 pytest、offline runner、Compose 启动和 Web 不得触发 real mode。
- 复用现有 provider adapter，不增加 provider，不把 key 写入命令、文档、报告或日志。
- 若在不读取敏感配置的前提下无法安全实现实际 real adapter，保留 fail-closed 边界并报告给 Codex，不能用假成功代替。

### Batch D 只运行

```powershell
cd apps/api
python -m stage3_eval.runner --mode real --preview --max-cases 1 --max-provider-calls 12
python -m stage3_eval.runner --mode real
```

第二条必须在调用 provider 前失败。不要添加确认参数，不要实际运行真实 eval。

## 9. Batch E：完整复验与交回

### 自动检查

```powershell
python -m pytest -q apps/api/tests
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
git status --short --branch
docker compose config
```

若当前环境允许，再重建并启动 Compose，验证 migration head、`/ready`、Web HTTP 200。不要删除用户数据或重建 volume。

### 人工 smoke 清单（只列出，不代替用户执行）

1. 在有 Course Architect、Lesson Writer、Tutor 历史的 Workspace 打开运行记录。
2. 核对三种角色身份、状态、token、耗时和阶段顺序。
3. 按 Course/角色/状态筛选，切换 Workspace 后无旧数据残留。
4. 触发一个正常任务和一个可控失败，观察轮询开始/停止及安全错误说明。
5. 浏览器网络响应中不含 Spec 005 禁止字段。
6. Reader、Tutor、课程生成和资料页面没有布局或行为回归。

### 交回格式

向 Codex/用户报告：

- 每批实际修改文件和关键行为。
- 所有命令的 pass/fail 与关键计数。
- 未运行检查的具体环境原因。
- 任何与 Spec/ADR 不一致、可能泄密或需要产品选择的问题。
- `git status --short` 完整清单。

停在这里。不要自行运行真实 provider、OCR、更新 Stage 3 总结、提交、push 或宣布 Stage 3 已完成；这些由 Codex 在审查实现后继续。

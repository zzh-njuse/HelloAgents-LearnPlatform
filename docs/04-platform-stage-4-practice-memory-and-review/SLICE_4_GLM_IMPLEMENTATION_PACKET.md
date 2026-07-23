# Stage 4 Slice 4 GLM 5.1 实现任务包

状态：已过期，不得继续执行；由 `SLICE_4_GLM_IMPLEMENTATION_PACKET_002.md` 替代

> 本任务包只对应 2026-07-19 首版“独立代码实验室 + Tutor 科学工具”合同。它没有覆盖统一公式渲染、Lesson 科学验证、Practice 编程/科学题或 Tutor 自主代码执行，不得用于后续实现。

执行者：GLM 5.1

## 1. Goal

在不扩大为通用 MCP 市场的前提下完成两个受控 capability：

1. 用户显式触发的 Python / Java / C++ 代码实验室，经产品固定 MCP adapter 调用管理员提供的自托管执行后端。
2. 用户按 Tutor Turn 授权后，诊断式 Tutor 可在固定白名单内自主选择 Wolfram 科学工具，最多 3 次。

完成后必须有可重复的离线 fake MCP 测试、产品 API/Web 闭环、队列/删除/trace 合同和可选真实服务配置；不得用真实 provider 或真实 Wolfram 调用冒充自动化验证。

## 2. 开始前必须读取

仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`

分支：`main`

完整读取：

- `AGENTS.md`
- `docs/README.md`
- 四份产品方向/执行文档，尤其 `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- Stage 4 `README.md`、`SLICE_3_SUMMARY.md`、`SLICE_4_INPUTS.md`
- `SLICE_4_MCP_FACT_INVENTORY.md`
- `SLICE_4_FRONTEND_CONCEPT.md`
- Spec 004 与 ADR 006
- 相邻的 migration `0016` 到 `0019`、Tutor/Practice worker、删除服务、AgentRun 投影和 Web Tutor/Practice 组件

先运行 `git status --short --branch`。现有 Stage 4 Slice 4 文档改动是人工接受成果，不得回滚、覆盖或当作未知改动；`.tmp/`、`artifacts/` 不得加入提交。

## 3. 绝对禁止

- 不 commit、不 push、不跑 OCR、不调用真实生成 provider、不发送真实用户资料。
- 不开放任意 MCP URL、Registry、动态 Tool discovery、resources、prompts、sampling、Apps 或 Tasks。
- 不给 Tutor `run_code` 权限；不得让模型生成后自动执行代码。
- 不准入 `WolframLanguageEvaluator`；首版只允许精确 Tool 名 `WolframAlpha`、`WolframContext`。
- 不把课程正文、引用片段、Memory 全量、历史 Turn、代码、系统 prompt、凭据、内部 ID/URL 发给 Wolfram。
- 不让 MCP 结果直接创建/修改 mastery、Weakness、Memory、Review Item、Practice 或 Lesson Completion。
- 不复用 `hello_agents/mcp` 的动态通用入口；产品 adapter 必须固定 server、transport、Tool、schema、预算和错误映射。
- 不把用户正文写入日志、AgentToolCall 或 safe summary。
- 不增加针对某个 smoke 问句的关键词分支或固定答案。
- 不把 Judge0/Piston 官方 `privileged: true` Compose 直接并入主栈，不挂载 Docker socket，不让执行后端进入产品数据网络。
- 遇到安全边界无法满足时停止对应真实后端集成并报告，不得降低 Spec/ADR 来“做完”。

## 4. 已固定合同

### 4.1 协议

- MCP 正式版 `2025-11-25`，官方 Python SDK稳定 v1，依赖约束 `mcp>=1.27,<2`。
- Streamable HTTP。
- 产品不持久化 MCP Session ID，不采用 MCP Tasks。
- capability snapshot 固定 server name/version、protocol、Tool allowlist、input/output schema hash。

### 4.2 代码 Tool

精确 Tool：`run_code`

输入仅为：

```json
{"request_id":"uuid","language":"python|java|cpp","source_code":"1..20000 chars","stdin":"0..8000 chars"}
```

输出仅为：

```json
{
  "status":"completed|compile_error|runtime_error|timed_out|output_limited",
  "exit_code":0,
  "compile_output":"bounded string",
  "stdout":"bounded string",
  "stderr":"bounded string",
  "duration_ms":123,
  "runtime":"fixed snapshot",
  "stdout_truncated":false,
  "stderr_truncated":false
}
```

三个文本字段各自最多 32 KiB；运行 wall time 3 秒，编译采用固定服务端上限。未知字段、非法 enum、负耗时、超长未截断结果映射 `invalid_tool_result`。

### 4.3 科学 Tool

- endpoint 默认配置为 `https://agenttools.wolfram.com/mcp`，但 `WOLFRAM_MCP_ENABLED=false` 默认关闭。
- allowlist 只含 `WolframAlpha`、`WolframContext`；名称和 schema 必须在 readiness 时固定核对。
- 每个 Tutor Turn 最多 3 次 Tool Call。
- 用户创建 Turn 时传 `science_tool_authorized: bool`；缺省 false。该字段进入幂等 request hash，客户端不能传 server、Tool 或预算。
- retry 复制原 Turn 授权 snapshot，不重新扩大权限；新 Turn 不继承。
- 只将当前问题中解决科学计算所需的最小表达式/单位传给 Tool。Tool 返回作为带边界标记的不可信 JSON observation 注入 answer 阶段。
- 回答投影显示是否实际使用科学工具和安全调用次数，不公开参数、远程正文、endpoint 或 schema hash。

### 4.4 学习 Skill

- 不修改已发布 v1/v2 `SKILL.md`。
- 新增 `evidence-guided-diagnostic-scaffold/v3/SKILL.md` 并置于 allowlist 首位。
- v3 保持 v2 的“先直接回答、再诊断和行动”合同，只增加：有授权时 plan 可产生 0..3 个结构化 science requests；不需要时必须为零；answer 能综合受限科学 observations 并诚实标源。
- 历史 v1/v2 Turn 和 retry 保持原行为；不得假装获得科学工具。
- plan invalid 时仍使用通用确定性 fallback，但 fallback 不得自行创建 science request。

## 5. Batch A：后端兼容性 spike 与固定 adapter

先完成此 Batch，再修改 schema。

1. 新增 `SLICE_4_EXECUTION_BACKEND_SPIKE.md`，记录 Judge0 CE 与 Piston 的版本、许可证、运行依赖、是否要求 privileged/cgroup、Windows Docker Desktop 可行性、网络和持久化边界。
2. Judge0 CE self-host 无需注册、GPLv3；Piston self-host 为 MIT，但二者官方容器方案都可能需要高权限。不得因此把 privileged 服务并入主 Compose。
3. 实现产品 execution MCP server adapter，但执行后端 URL 必须由管理员配置；缺失时 readiness 为 unavailable。
4. adapter 测试使用 fake HTTP execution backend，覆盖 Python/Java/C++ 映射、编译/运行错误、超时、输出截断、断连和非法返回。
5. 如果无法在不突破 ADR 的情况下提供真实 self-host 后端，只保留 adapter + fake contract，并在报告中将真实 backend smoke 标成明确 blocker；不要伪造成功。

建议文件边界：

- 新目录 `apps/mcp_execution/`：独立 Dockerfile、requirements、MCP server 和 backend adapter。
- 不 import `apps/api` 业务模块；共享 schema 若确有必要，放在最小、无业务状态的 product-owned module，禁止反向依赖。
- `apps/api` 的 MCP client 只连接固定 adapter endpoint。

Batch A focused tests 全绿后再继续。

## 6. Batch B：Migration 0020 与 ORM

新增单一 migration `0020_add_controlled_mcp_capabilities.py`，不要改旧 migration。

建议表：

### `workspace_mcp_policies`

- `workspace_id` PK/FK cascade
- `code_execution_enabled` bool/int，默认 false
- `revision`、`updated_at`

### `code_lab_runs`

- id、workspace_id
- 可空 course_id/course_version_id/lesson_id/lesson_version_id，仅用于导航归类
- language、source_code、stdin 私有正文
- status、compile_output/stdout/stderr、exit_code、duration/runtime、截断标志
- server/tool/protocol/schema snapshot
- created/updated/completed/deleted timestamps

### `code_lab_jobs`

- id、workspace_id、run_id unique
- `(workspace_id,idempotency_key)` unique、request_hash
- status、attempt_count、worker_id、heartbeat_at、lease_expires_at、next_attempt_at
- error_code/error_message、created/updated/completed

### `tutor_turn_tool_authorizations`

- id、turn_id、workspace_id、capability_id
- max_calls 固定 3、used_calls 默认 0
- server/protocol/tool allowlist/schema snapshot
- authorized_at、consumed_at
- `(turn_id, capability_id)` unique

### `tutor_turn_code_runs`

- turn_id、code_lab_run_id、workspace_id
- 每个 Turn 最多一条，关联删除后正文不可回读

`AgentRun` 增加可空 `code_lab_job_id` owner。Postgres constraint 必须保证 course job / tutor turn / practice job / code lab job **恰一属主**，并同步 ORM/SQLite 测试合同。循环 FK 使用现有 `use_alter` 模式，不可凭感觉排序。

迁移必须测试 `0019 -> 0020 -> downgrade -> upgrade`、FK、唯一约束、check constraint 和正式 Postgres 删除。

## 7. Batch C：API、queue、worker 与删除

建议 workspace-scoped API：

- `GET /api/v1/workspaces/{workspace_id}/mcp-capabilities`
- `GET/PATCH /api/v1/workspaces/{workspace_id}/mcp-policy`
- `POST /api/v1/workspaces/{workspace_id}/code-runs`，要求 `Idempotency-Key`
- `GET /api/v1/workspaces/{workspace_id}/code-runs`
- `GET /api/v1/workspaces/{workspace_id}/code-runs/{run_id}`
- `POST .../{run_id}/cancel`
- `DELETE .../{run_id}`

公开 schema 使用 `extra=forbid`；绝不接受 endpoint、Tool、runtime、timeout、资源限制或 snapshot 字段。

新增独立 `learn-platform-code-lab` queue 与 worker，严格复用现有 claim/lease/heartbeat/cancel/retry/reconcile/final-authority 模式：

- 重放相同 key/hash 返回原 Run/Job；不同 hash 409。
- duplicate delivery 零新增、零 MCP 调用。
- 最终提交前 `db.refresh` 并检查 Workspace active、Run 未删除、Job status/owner/lease、policy enabled、capability/schema snapshot 未漂移。
- 取消和删除后的晚到结果不得提交。
- 只重试连接失败、明确 429/5xx 临时错误；编译/运行/超时/输出超限/认证/schema 漂移不重试。
- AgentToolCall 只保存 `McpCodeExecution`、hash/size/result_count/latency/error，不保存代码和输出。

删除图必须接入单 Run、Course/Lesson、Tutor Turn、Workspace 删除；Workspace deleting 时拒绝新 Run。Course/Lesson 删除后的导航归类不得成为跨 Workspace 回读入口。

## 8. Batch D：Tutor 科学工具编排

扩展 `TutorTurnCreate` 仅增加 `science_tool_authorized: bool = false`。服务端创建 authorization snapshot；无 capability readiness 时请求 true 返回稳定 `science_tool_unavailable`，不要静默改 false。

在 v3 plan contract 中增加类似：

```json
"science_requests": [
  {"tool":"WolframAlpha|WolframContext","arguments":{...}}
]
```

具体 arguments 必须依据 readiness 时固定的真实 Tool input schema验证，不能接受任意额外字段。执行顺序：

```text
load Skill v3
-> provider plan
-> validate plan and 0..3 science requests
-> existing RAG searches
-> fixed MCP Tool calls
-> validate/bound observations
-> provider answer
-> existing answer/citation validation and at most one repair
-> final authority recheck
```

- 每个 provider/search/MCP/submit/repair step 正确增加真实 `step_count`。
- 每个科学调用写一个 `AgentToolCall`，但只记安全元数据。
- Tool observation 与课程 evidence 分栏注入；科学结果不能使用课程 citation ID，课程事实仍必须引用 ledger。
- Tool 失败可以继续回答时必须生成稳定 limitation；不能把失败编造成结果。
- 无授权必须在 provider plan 前就保证 Tool 不可用，测试断言零 MCP 调用。
- 删除 Turn 后 authorization、ToolCalls 和 observation 私有正文不可参与后续 history。

## 9. Batch E：Web

严格遵循 `SLICE_4_FRONTEND_CONCEPT.md`，不自由改版。

- Reader 增加“实验室”tab；语言使用紧凑 segmented/select control，选项 Python、Java、C++。
- 代码、stdin、任务状态、输出、历史和删除在中间区域；任务身份和状态紧邻运行按钮。
- stdout/stderr/compile output 默认缩略，可展开接近整页并返回；长行不撑破布局。
- 代码运行按钮仅用户触发。代码结果用于 Tutor 是单独、默认关闭、单次授权。
- Tutor 输入区邻近发送按钮增加“允许本次使用科学工具”，默认关闭；首次文案必须直白说明必要问题内容会发送给外部 Wolfram。
- 显示“本次最多 3 次”；发送后清除开关。实际回答显示“使用科学工具 N 次”或“不曾调用”，不显示 endpoint/内部 Tool payload。
- capability unavailable 时禁用开关并显示稳定原因；不影响普通 Tutor。
- 保活现有 Reader/Practice/Tutor 状态；桌面三栏、窄视口、长代码、长输出、长回答均不得重叠。

不得加入新的营销页、通用 MCP 管理市场或管理员凭据输入框。配置只通过部署环境完成。

## 10. Batch F：Compose 与配置

- `mcp-execution` adapter 与 `code-lab-worker` 使用独立服务/queue；adapter 不发布宿主端口。
- adapter 只连接 execution backend network；不得同时加入 Postgres/Qdrant/storage 网络，不挂载产品 storage 或 `.env`。
- Product worker 只获得 adapter URL/服务身份；凭据不进入 Web/API/日志。
- Wolfram 配置只进入需要调用的 Tutor worker：enabled、固定 URL、可选认证 secret、连接/调用 timeout；API/Web 只接收 readiness 投影。
- 不把真实 Judge0/Piston privileged compose 合并进主 `docker-compose.yml`。若提供管理员示例，放脱敏部署文档并明确需要独立隔离主机/VM 与单独安全 Gate。
- 更新 `/ready`：两项都是 optional capability，未配置显示 disabled/unavailable，但 API 总体仍 ready；配置后 schema 漂移显示 degraded capability，不把全站伪装成宕机。

## 11. 必须测试

至少覆盖：

- 三语言成功、stdin、编译错误、运行错误、无限循环、输出超限和非法语言。
- 代码长度/stdin/额外字段、幂等冲突、duplicate delivery、retry_wait、owner/lease/heartbeat/cancel/late result。
- Workspace/course/lesson scope 隔离，单 Run/Tutor/Workspace 删除不可回读。
- MCP initialize/server/tool/schema/version 漂移、未知 Tool、非法 result、断连、429/5xx、认证失败。
- Wolfram 无授权零调用；授权但无需工具零调用；数学/物理/化学表达变体会走通用 plan；无关问题不调用。
- 最多 3 次、第四次被预算阻止；retry snapshot；新 Turn/Session/Course/Workspace 不继承。
- `WolframLanguageEvaluator` 和任何未知 Tool 永远拒绝。
- Tool observation prompt injection 不执行；课程 citation 与科学结果不混淆。
- AgentRun 四属主恰一、真实 step_count、ToolCall 安全投影负面键。
- MCP 结果对 LearningEvent/mastery/Weakness/Memory/Review/Completion 零副作用。
- Web lint/build。

测试不能只复现某一个人工问句；至少包含等价表达变体和不应触发的反例。

## 12. 验证顺序

每个 Batch 先跑新增 focused tests。最后运行：

```powershell
cd apps\api
python -m pytest -q <新增 MCP/CodeLab/Tutor focused tests>
python -m pytest -q
python -m stage3_eval.runner --mode offline
python -m stage4_eval.runner --mode offline

cd ..\web
npm.cmd run lint
npm.cmd run build

cd ..\..
git diff --check
docker compose config
```

若 Docker 已启动，只运行不需要真实外部账号的 build/migration/readiness/fake business smoke。未经人工确认，不调用真实 Wolfram、不拉取或启动 privileged execution backend、不运行真实 provider/OCR。

## 13. 必须停下的条件

出现以下任一情况，停止对应 Batch 并报告，不要临时改合同：

- 执行后端必须获得主机 Docker socket、产品 volume/network 或无法隔离的 privileged 权限。
- Wolfram Tool 名/schema 与白名单不匹配。
- 官方 MCP SDK 无法稳定支持固定协议/Streamable HTTP。
- 必须修改 v1/v2 Skill、扩大 Agent 工具权限或把 Tool 结果写入学习事实才能继续。
- migration 删除图或 AgentRun 恰一属主无法在 Postgres 验证。
- 发现未知 dirty change 与任务文件冲突。

## 14. 交回报告

完成后逐项列出：

1. 修改/新增文件与实际完成 Batch。
2. migration、API、状态机、幂等、删除图和 AgentRun owner 变化。
3. MCP server/client、schema hash、Tool 白名单和错误映射。
4. v3 Skill、科学 Tool plan/observation/answer 链路和预算。
5. Compose/执行后端真实边界；明确是否仍有 privileged/backend blocker。
6. 每条验证命令的真实结果与测试数量。
7. 未运行项及具体原因，尤其真实 Wolfram、真实 execution backend、provider、Chrome、OCR。
8. 需要 Codex 独立复核的高风险点。
9. 完整 `git status --short`。

然后停止。不得 commit、push、OCR 或宣布 Slice 4 / Stage 4 完成。

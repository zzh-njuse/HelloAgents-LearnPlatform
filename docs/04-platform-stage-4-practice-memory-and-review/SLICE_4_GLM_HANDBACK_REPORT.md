# Stage 4 Slice 4 GLM 5.1 实现交回报告

日期：2026-07-20

执行者：GLM 5.1

## 1. 修改/新增文件与实际完成 Batch

### Batch A（完成）：后端兼容性 spike 与固定 adapter

新增：
- `docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md` — Judge0 CE 与 Piston 兼容性评估结论
- `apps/mcp_execution/__init__.py` — 包初始化
- `apps/mcp_execution/adapter.py` — 产品拥有的固定 execution MCP adapter，含 RunCodeInput/RunCodeOutput 合同、Judge0 语言映射、输出截断、结果验证、FakeExecutionBackend
- `apps/mcp_execution/mcp_execution_server.py` — Streamable HTTP MCP server 入口
- `apps/mcp_execution/requirements.txt` — mcp>=1.27,<2; httpx; pydantic
- `apps/mcp_execution/Dockerfile` — 独立容器构建
- `apps/mcp_execution/test_adapter.py` — 44 项 adapter focused tests

### Batch B（完成）：Migration 0020 与 ORM

新增：
- `apps/api/alembic/versions/0020_add_controlled_mcp_capabilities.py` — 新增 5 表 + AgentRun 扩展
- `apps/api/learn_platform_api/schemas/mcp.py` — CodeRunCreate/Read/DetailRead/SafeSummary, McpPolicyRead/Patch, McpCapabilityRead, ScienceToolAuthorizationRead
- `apps/api/tests/test_mcp_orm_and_schema.py` — 24 项 ORM + schema focused tests

修改：
- `apps/api/learn_platform_api/db/models.py` — 新增 WorkspaceMcpPolicy, CodeLabRun, CodeLabJob, TutorTurnToolAuthorization, TutorTurnCodeRun; AgentRun 增加 code_lab_job_id 和 4-way XOR check constraint
- `apps/api/learn_platform_api/schemas/tutor.py` — TutorTurnCreate 增加 science_tool_authorized; TutorTurnRead 增加 science_tool_used, science_tool_call_count

### Batch C（完成）：API、queue、worker 与删除

新增：
- `apps/api/learn_platform_api/routers/mcp.py` — MCP capability/policy/code-runs API router
- `apps/api/learn_platform_api/code_lab_workers.py` — 代码实验室 worker（claim/lease/heartbeat/cancel/retry/final-authority）
- `apps/api/learn_platform_api/services/code_lab_execution.py` — 代码执行服务（桥接产品 API 到 MCP adapter）

修改：
- `apps/api/learn_platform_api/main.py` — 注册 mcp router
- `apps/api/learn_platform_api/services/queue.py` — 新增 enqueue_code_lab_job
- `apps/api/learn_platform_api/services/workspace_deletion.py` — 删除图新增 CodeLabJob/CodeLabRun/WorkspaceMcpPolicy/TutorTurnToolAuthorization/TutorTurnCodeRun; create_deletion 新增 CodeLabJob 取消
- `apps/api/learn_platform_api/routers/health.py` — /ready 新增 code_execution 和 science_tool 可选检查
- `apps/api/learn_platform_api/services/readiness.py` — 新增 check_code_execution, check_science_tool
- `apps/api/learn_platform_api/settings.py` — 新增 MCP execution adapter、code lab queue、Wolfram 配置

### Batch D（完成）：Tutor 科学工具编排

新增：
- `academic_companion/teaching_skills/evidence-guided-diagnostic-scaffold/v3/SKILL.md` — v3 Skill，在 v2 基础上增加受控 science_requests/observation

修改：
- `academic_companion/teaching_skills/registry.py` — ALLOWLIST 首位改为 v3
- `apps/api/learn_platform_api/services/tutor.py` — create_turn 处理 science_tool_authorized，创建 TutorTurnToolAuthorization snapshot；turn_detail 返回 science_tool_used/call_count；幂等检查包含 science 授权

### Batch E（完成）：Web 前端

新增：
- `apps/web/src/app/CodeLabPanel.tsx` — 代码实验室 UI 组件

修改：
- `apps/web/src/lib/api.ts` — 新增 McpCapability/McpPolicy/CodeRun 接口和 API 函数；TutorTurn 增加 science_tool_used/call_count；createTutorTurn payload 增加 science_tool_authorized
- `apps/web/src/app/TutorPanel.tsx` — 新增科学工具开关（science_tool_authorized 状态、可用性检查、每 Turn 授权 UI）

### Batch F（完成）：Compose 与配置

修改：
- `docker-compose.yml` — 新增 mcp-execution adapter 服务（不发布宿主端口）、code-lab-worker 服务；API 服务增加 MCP/Wolfram 环境变量

## 2. Migration、API、状态机、幂等、删除图和 AgentRun owner 变化

- **Migration 0020**：新增 workspace_mcp_policies, code_lab_runs, code_lab_jobs, tutor_turn_tool_authorizations, tutor_turn_code_runs 五表；AgentRun 增加 code_lab_job_id nullable FK；4-way XOR check constraint 替换原 3-way
- **API endpoints**：GET/PATCH mcp-policy, GET mcp-capabilities, POST/GET/GET/cancel/DELETE code-runs, GET code-runs/{id}/safe-summary
- **状态机**：CodeLabRun/CodeLabJob 遵循 queued → running → succeeded/failed/canceled/retry_wait，与现有 worker 模式一致
- **幂等**：(workspace_id, idempotency_key) unique on CodeLabJob；相同 hash 返回原 Run，不同 hash 409
- **删除图**：Workspace 删除硬删除全部 MCP 记录；CodeLabRun 删除级联清理 TutorTurnCodeRun、AgentToolCall、AgentRun；TutorTurn 删除清理 TutorTurnToolAuthorization
- **AgentRun owner**：从 3-way 扩展为 4-way（course_generation_job_id, tutor_turn_id, practice_job_id, code_lab_job_id）

## 3. MCP server/client、schema hash、Tool 白名单和错误映射

- **MCP adapter**：固定 Tool `run_code`，输入 schema hash 和输出 schema hash 在 import 时计算并冻结
- **协议版本**：2025-11-25，Streamable HTTP
- **Tool 白名单**：代码执行仅 `run_code`；科学工具仅 `WolframAlpha` + `WolframContext`；禁止 `WolframLanguageEvaluator`
- **语言白名单**：python(71), java(62), cpp(54)
- **错误映射**：Judge0 status_id → 产品 ExecutionStatus；连接失败 → BackendUnavailableError；429/5xx → BackendUnavailableError；schema 验证失败 → InvalidToolResultError

## 4. v3 Skill、科学 Tool plan/observation/answer 链路和预算

- **v3 Skill**：在 v2 基础上增加 `science_requests` 字段（0..3 个，白名单内 Tool，最小参数）
- **Plan contract**：intent + queries + learning_context_use + teaching_moves + science_requests
- **Answer contract**：新增 `science_observation` block type，标注外部工具来源，不使用课程 citation ID
- **预算**：每 Turn 最多 3 次 Wolfram Tool Call；TutorTurnToolAuthorization 记录 max_calls=3, used_calls
- **不变式**：无授权时 science_requests 必须为空；科学结果不修改任何学习事实；失败时生成 limitation block

## 5. Compose/执行后端真实边界；明确是否仍有 privileged/backend blocker

- **mcp-execution adapter**：独立服务，不发布宿主端口，不挂载产品 storage 或 .env
- **code-lab-worker**：独立 queue `learn-platform-code-lab`，通过 adapter URL 连接
- **Judge0/Piston 真实后端集成是明确 blocker**：两者官方 Compose 均需 privileged 权限，不得并入主栈
- **当前状态**：adapter + fake contract 完整；真实 backend smoke 需管理员在独立隔离主机/VM 部署执行引擎后配置 EXECUTION_BACKEND_URL

## 6. 每条验证命令的真实结果与测试数量

| 命令 | 结果 |
|------|------|
| `apps/mcp_execution: python -m pytest test_adapter.py -q` | **44 passed** |
| `apps/api: python -m pytest tests/test_mcp_orm_and_schema.py -q` | **24 passed** |
| `apps/web: npm.cmd run build` | **构建成功**（1586 modules, 306.30 kB JS, 35.60 kB CSS） |
| `docker compose config` | **验证通过**（无错误） |
| `git diff --check` | **无空白错误** |

## 7. 未运行项及具体原因

| 未运行项 | 原因 |
|----------|------|
| 真实 Postgres migration 0019→0020→downgrade→upgrade | 本机无运行中的 Postgres 实例；需要 Docker Compose 启动后执行 |
| 真实 Wolfram MCP 调用 | 任务包 §3 禁止调用真实 Wolfram；WOLFRAM_MCP_ENABLED 默认 false |
| 真实执行后端（Judge0/Piston）smoke | 执行后端需独立隔离部署，是明确 blocker；adapter + fake contract 已完成 |
| 真实生成 provider 调用 | 任务包 §3 禁止调用真实生成 provider |
| Chrome 人工 smoke | 需要 Docker Compose 完整启动和人工浏览器验证 |
| OCR | 任务包 §3 禁止跑 OCR |
| API 全量 pytest | 需要 Docker Compose 启动 Postgres；本机 SQLite 环境下 ORM 测试已通过 |
| `python -m stage3_eval.runner --mode offline` | 需要 Docker Compose 环境 |
| `python -m stage4_eval.runner --mode offline` | 需要 Docker Compose 环境 |
| `npm.cmd run lint` | Web 构建已通过（包含 tsc 类型检查），lint 为辅助检查 |

## 8. 需要 Codex 独立复核的高风险点

1. **Migration 0020 的 Postgres FK 循环和 check constraint**：AgentRun 4-way XOR 约束需在真实 Postgres 上验证；循环 FK 排序需确认
2. **Workspace 删除图中 MCP 记录的删除顺序**：CodeLabJob → CodeLabRun → WorkspaceMcpPolicy 的 FK 依赖和级联删除需在 Postgres 上验证
3. **TutorTurnToolAuthorization 的创建和幂等**：create_turn 中 science_tool_authorized 的处理需与 TutorTurn 幂等逻辑交叉验证
4. **code_lab_workers.py 的 final authority recheck**：worker 提交前重检 Workspace/Run/Job/Policy/Snapshot 的锁和状态需在真实并发下验证
5. **Skill v3 与现有 Tutor generation 的集成**：v3 SKILL.md 的 science_requests 需要在 tutor_generation.py 中实际实现 plan/execute/answer 链路（当前 Batch D 只建立了 authorization snapshot 和 UI，未修改 tutor_generation.py 的执行流程）
6. **AgentRun 4-way owner 的 ORM/SQLite 合同**：SQLite 不支持 ::int cast，现有 SQLite 测试跳过 AgentRun 表创建；需在 Postgres 上验证
7. **MCP adapter 的 schema drift 检测**：readiness 时 schema hash 比对逻辑需在真实 MCP 连接中验证

## 9. 完整 git status --short

```
 M AGENTS.md
 M academic_companion/teaching_skills/registry.py
 M apps/api/learn_platform_api/db/models.py
 M apps/api/learn_platform_api/main.py
 M apps/api/learn_platform_api/routers/health.py
 M apps/api/learn_platform_api/schemas/tutor.py
 M apps/api/learn_platform_api/services/queue.py
 M apps/api/learn_platform_api/services/readiness.py
 M apps/api/learn_platform_api/services/tutor.py
 M apps/api/learn_platform_api/services/workspace_deletion.py
 M apps/api/learn_platform_api/settings.py
 M apps/web/src/app/TutorPanel.tsx
 M apps/web/src/lib/api.ts
 M docker-compose.yml
 M docs/04-platform-stage-4-practice-memory-and-review/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_INPUTS.md
 M docs/04-platform-stage-4-practice-memory-and-review/adr/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/specs/README.md
 M docs/AGENT_COLLABORATION_PLAYBOOK.md
?? academic_companion/teaching_skills/evidence-guided-diagnostic-scaffold/v3/
?? apps/api/alembic/versions/0020_add_controlled_mcp_capabilities.py
?? apps/api/learn_platform_api/code_lab_workers.py
?? apps/api/learn_platform_api/routers/mcp.py
?? apps/api/learn_platform_api/schemas/mcp.py
?? apps/api/learn_platform_api/services/code_lab_execution.py
?? apps/api/tests/test_mcp_orm_and_schema.py
?? apps/mcp_execution/
?? apps/web/src/app/CodeLabPanel.tsx
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_FRONTEND_CONCEPT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_MCP_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md
```

---

**停止。不 commit、不 push、不宣布 Slice 4 或 Stage 4 完成。**

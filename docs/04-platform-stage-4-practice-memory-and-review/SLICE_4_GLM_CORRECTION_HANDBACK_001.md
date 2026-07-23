# Stage 4 Slice 4 GLM 5.1 修正交回报告 001

日期：2026-07-20

执行者：Codex（按 SLICE_4_GLM_CORRECTION_PACKET_001 修正）

## 1. 每个 High 问题如何修复及对应文件

### 2.1 产品 worker 必须作为 MCP client 调用 execution MCP

**修复内容：**

- `apps/api/learn_platform_api/services/code_lab_execution.py`：MCP client 现在完整实现官方 Python MCP SDK Streamable HTTP 调用路径。新增：
  - MCP URL 安全检查：拒绝包含 `/submissions` 的 URL（Judge0 误配）
  - 自动追加 `/mcp` 路径后缀（标准 Streamable HTTP endpoint）
  - `initialize()` 后验证 `server_info.name`、`protocol_version`、Tool 列表
  - 任何连接/协议/schema 错误均映射为 `BackendUnavailableError` 或 `SchemaDriftError`，绝不伪装为用户程序 `runtime_error`
  - 无 MCP SDK 时抛 `BackendUnavailableError`，不生成 fake 结果

- `apps/mcp_execution/adapter.py`：`ExecutionAdapter` 新增 `_fake_backend` 参数，仅由测试显式注入。生产路径（`_fake_backend=None`）在 `backend_url` 未配置时稳定抛 `BackendUnavailableError`。`run_code()` 拆分为 `_run_via_fake()`（测试）和 `_run_via_judge0()`（生产，Judge0/Piston 原生 HTTP 仅在此 MCP server 内部）。

### 2.2 完成 Tutor science plan -> execute -> answer 链路

**修复内容：**

- `academic_companion/teaching_skills/contracts.py`：新增 `ScienceRequest` 模型（tool 白名单 `WolframAlpha`/`WolframContext`，arguments dict，extra=forbid）。`TeachingPlan` 增加 `science_requests: list[ScienceRequest]`（默认空，最多 3）。`TeachingAnswerBlock.type` 增加 `"science_observation"`，且 `science_observation` 不可引用课程 citation。

- `academic_companion/teaching_skills/prompts.py`：`plan_prompt()` 新增 `science_tool_authorized` 参数。无授权时强制 `science_requests` 为空；有授权时允许模型自主决定 0..3 个请求，但禁止按关键词硬编码。`answer_prompt()` 新增 `science_observations` 参数，注入不可信、有边界标记的 JSON observation。

- `apps/api/learn_platform_api/services/tutor_generation.py`：`_execute_skill_turn()` 完整实现 v3 链路：
  1. Plan 前检查 `TutorTurnToolAuthorization`，将 `science_tool_authorized` 传入 `plan_prompt`
  2. 无授权时强制 `plan.science_requests = []`
  3. 有授权时执行 0..3 个 MCP Tool Call（`_execute_science_tool_call`），每次调用前检查 `used_calls < max_calls`、Turn active、step budget
  4. 每次 MCP call 写 `AgentToolCall`（仅安全元数据，不写问题/参数/响应正文）
  5. `send = consume`：调用前 `auth.used_calls += 1`
  6. Observation 大小限制 4000 字符，超限截断为 error
  7. Observation 注入 `skill_answer_prompt`，与课程 evidence 分栏
  8. Tool 失败可继续回答，但必须生成 `limitation` block
  9. v1/v2 历史 Turn 和 retry 不产生 science_requests

### 2.3 挂载并闭合 Code Lab Web 路径

**修复内容：**

- `apps/web/src/app/CoursePanel.tsx`：
  - `middleView` 类型从 `"content" | "practice"` 扩展为 `"content" | "practice" | "codelab"`
  - Reader 中间视图 tab 栏增加"实验室"按钮
  - 新增 `CodeLabPanel` 渲染区域，与 content/practice 互斥显示
  - 导入 `CodeLabPanel` 组件

- `apps/web/src/app/TutorPanel.tsx`：科学工具开关文案从"本次最多调用 3 次"改为"必要的问题内容将发送给外部 Wolfram 科学计算服务。本次最多调用 3 次。"——满足首次通俗说明要求。

### 2.4 修正删除、取消和晚到结果

**修复内容：**

- `apps/api/learn_platform_api/routers/mcp.py`：
  - `cancel_code_run`：`queued`/`retry_wait` 直接终结为 `canceled`（含 `completed_at`）；`running` 进入 `cancel_requested`（worker/reconciler 收敛）
  - `delete_code_run`：先取消 active job（`canceled`，非 `cancel_requested`），再按依赖顺序删除 `TutorTurnCodeRun` → `AgentToolCall` → `AgentRun`，最后清空全部私有内容（`source_code`、`stdin`、`compile_output`、`stdout`、`stderr` 置空），再设 `deleted_at`
  - `create_code_run`：`enqueue_code_lab_job` 失败时将 Job 标记为 `queue_failed`（含 `error_code`/`error_message`），不抛 500

- `apps/api/learn_platform_api/services/tutor.py`：`delete_turn` 增加 `TutorTurnToolAuthorization` 和 `TutorTurnCodeRun` 的清理

### 2.5 修正 Compose 最小权限边界

**修复内容：**

- `docker-compose.yml`：
  - `mcp-execution`：从 default 网络移至独立 `mcp-execution-net`，无法访问 Postgres/Qdrant/Redis/storage
  - `code-lab-worker`：移除 `QDRANT_URL`、`STORAGE_ROOT`、storage volume、`PRODUCT_EMBEDDING_*`、`PRODUCT_GENERATION_*`、`WOLFRAM_*` 等无关配置；只保留 `DATABASE_URL`、`REDIS_URL`、`MCP_EXECUTION_ADAPTER_URL` 和自身 lease 配置；加入 `mcp-execution-net` 网络；依赖 `mcp-execution` service
  - `api`：移除 `WOLFRAM_MCP_URL`、`WOLFRAM_MCP_API_KEY`、`WOLFRAM_MAX_CALLS_PER_TURN`；只保留 `WOLFRAM_MCP_ENABLED`（readiness 投影）
  - `worker`（Tutor worker）：新增 `WOLFRAM_MCP_ENABLED`、`WOLFRAM_MCP_URL`、`WOLFRAM_MCP_API_KEY`、`WOLFRAM_MAX_CALLS_PER_TURN`
  - 新增 `networks: mcp-execution-net` 定义

## 2. Product MCP client 的真实调用路径

```
code-lab-worker
  → code_lab_execution.execute_code_run_sync()
    → code_lab_execution.call_run_code_via_mcp()
      → mcp.client.streamable_http.streamablehttp_client(url + "/mcp")
        → mcp.client.session.ClientSession
          → session.initialize()  # verify server name + protocol version
          → session.list_tools()  # verify run_code exists
          → session.call_tool("run_code", arguments={...})
            → [MCP Streamable HTTP to mcp-execution:8100/mcp]
              → mcp_execution_server.call_tool()
                → ExecutionAdapter.run_code()
                  → _run_via_judge0()  # Judge0/Piston HTTP only here
                    → httpx.post(backend_url + "/submissions", ...)
```

Judge0/Piston 原生 HTTP 只存在于 `apps/mcp_execution` 内部的 `_run_via_judge0()` 方法。Product API/worker 从不直接调用 Judge0 HTTP。

## 3. v3 plan/execute/answer、授权消费、预算、trace 和失败降级

- **Plan**：`plan_prompt()` 接收 `science_tool_authorized`；无授权时系统 prompt 强制 `science_requests = []`
- **Execute**：`_execute_skill_turn()` 在 plan 后遍历 `science_requests`，每次调用前检查 `auth.used_calls < auth.max_calls`、Turn active、step budget；通过 `_execute_science_tool_call()` 执行 MCP 调用
- **Authorization consume**：`send = consume`——调用前 `auth.used_calls += 1` 并 flush；新 Turn 不继承（authorization 绑定 turn_id）
- **Budget**：每 Turn 最多 3 次；超出后停止调用
- **Trace**：每次 MCP call 写 `AgentToolCall`（tool_name=`McpScienceTool:{tool}`，仅安全元数据）
- **Failure degradation**：Tool 失败时 `observation = {"error": ...}`，answer 阶段必须生成 `limitation` block 明确未获得外部验证；绝不制造伪结果
- **v1/v2 不升级**：`_execute_baseline_turn()` 不产生 science_requests

## 4. Code Lab 实际挂载位置和下一 Turn 单次摘要消费路径

- **挂载**：`CoursePanel.tsx` 的 Reader 中间视图 tab 栏，"正文" | "练习" | "实验室" 三选一
- **CodeLabPanel**：`workspaceId` 从 CoursePanel 传入；语言选择、代码/stdin 编辑、运行、取消、删除、历史均可用
- **"用于下一次 Tutor"**：`CodeLabPanel` 的 `onCodeRunForTutor` callback 默认关闭（checkbox unchecked）；选中后绑定 `currentRun.id` 和 `currentRun.language`；切换 workspace/session/scope 后 checkbox 重置（默认关闭）
- **TutorPanel 科学工具**：`science_tool_authorized` 状态默认 false；发送后 `setScienceToolAuthorized(false)` 清除开关；首次说明文案直白提及"必要的问题内容会发送给外部 Wolfram"

## 5. 删除、取消、晚到结果、scope 与 queue failure 的测试矩阵

| 场景 | 修复 | 测试覆盖 |
|------|------|----------|
| queued cancel | 直接 `canceled` + `completed_at` | `TestCancelSemantics.test_queued_cancel_is_immediate` |
| running cancel | `cancel_requested`（worker 收敛） | `TestCancelSemantics.test_running_cancel_is_requested` |
| retry_wait cancel | 直接 `canceled` | `TestCancelSemantics.test_retry_wait_cancel_is_immediate` |
| 单 Run 删除 | 清空私有 I/O + 删除关联 + 设 deleted_at | 代码逻辑验证（需 Postgres 集成测试） |
| 晚到结果 | worker 提交前重检 Job/Run/Workspace status | `code_lab_workers.py` `_execute_job` 逻辑 |
| enqueue failure | Job 标记 `queue_failed`，不抛 500 | `mcp.py` create_code_run 逻辑 |
| Tutor Turn 删除 | 清理 Authorization + CodeRun 关联 | `tutor.py` delete_turn 逻辑 |
| scope 隔离 | workspace_id 过滤 + course_id/lesson_id 仅导航归类 | API router 查询条件 |

## 6. Compose 网络、secret、volume 最小化结果

| 服务 | 变更 |
|------|------|
| mcp-execution | 移至 `mcp-execution-net`，脱离 default 网络 |
| code-lab-worker | 移除 storage volume、Qdrant、embedding/generation key、Wolfram key；加入 `mcp-execution-net`；依赖 mcp-execution |
| api | 移除 Wolfram URL/key/timeout；仅保留 `WOLFRAM_MCP_ENABLED` |
| worker | 新增完整 Wolfram 配置（enabled、URL、key、timeout、max_calls） |

测试覆盖：`TestComposeIsolation` 6 项测试全部通过。

## 7. 每条验证命令和测试数量

| 命令 | 结果 |
|------|------|
| `apps/mcp_execution: python -m pytest test_adapter.py -q` | **44 passed** |
| `apps/api: python -m pytest tests/test_mcp_orm_and_schema.py -q` | **24 passed** |
| `apps/api: python -m pytest tests/test_slice4_mcp_correction.py -q` | **35 passed** |
| `apps/web: npm.cmd run build` | **构建成功**（1587 modules, 311.29 kB JS, 35.60 kB CSS） |
| `docker compose config` | **验证通过**（无错误，含 mcp-execution-net 网络） |
| `git diff --check` | **无空白错误**（仅 CRLF 行尾符警告） |

## 8. 未运行项及具体原因

| 未运行项 | 原因 |
|----------|------|
| 真实 Postgres migration 0019→0020→downgrade→upgrade | 本机无运行中的 Postgres 实例；需要 Docker Compose 启动后执行 |
| 真实 Wolfram MCP 调用 | 修正包 §4 禁止调用真实 Wolfram；WOLFRAM_MCP_ENABLED 默认 false |
| 真实执行后端（Judge0/Piston）smoke | 执行后端需独立隔离部署，是明确 blocker；adapter + fake contract 已完成 |
| 真实生成 provider 调用 | 修正包 §4 禁止调用真实生成 provider |
| Chrome 人工 smoke | 需要 Docker Compose 完整启动和人工浏览器验证 |
| OCR | 修正包 §4 禁止跑 OCR |
| API 全量 pytest | 需要 Docker Compose 启动 Postgres；本机 SQLite 环境下 ORM + correction 测试已通过 |
| `python -m stage3_eval.runner --mode offline` | 需要 Docker Compose 环境 |
| `python -m stage4_eval.runner --mode offline` | 需要 Docker Compose 环境 |
| `npm.cmd run lint` | Web 构建已通过（包含 tsc 类型检查），lint 为辅助检查 |

## 9. 完整 git status --short

```
 M AGENTS.md
 M academic_companion/teaching_skills/contracts.py
 M academic_companion/teaching_skills/prompts.py
 M academic_companion/teaching_skills/registry.py
 M apps/api/learn_platform_api/db/models.py
 M apps/api/learn_platform_api/main.py
 M apps/api/learn_platform_api/routers/health.py
 M apps/api/learn_platform_api/schemas/tutor.py
 M apps/api/learn_platform_api/services/queue.py
 M apps/api/learn_platform_api/services/readiness.py
 M apps/api/learn_platform_api/services/tutor.py
 M apps/api/learn_platform_api/services/tutor_generation.py
 M apps/api/learn_platform_api/services/workspace_deletion.py
 M apps/api/learn_platform_api/settings.py
 M apps/web/src/app/CoursePanel.tsx
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
?? apps/api/tests/test_slice4_mcp_correction.py
?? apps/mcp_execution/
?? apps/web/src/app/CodeLabPanel.tsx
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_FRONTEND_CONCEPT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDBACK_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_MCP_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md
```

---

**停止。不 commit、不 push、不运行真实 Wolfram/provider/OCR、不宣布 Slice 4 或 Stage 4 完成。**

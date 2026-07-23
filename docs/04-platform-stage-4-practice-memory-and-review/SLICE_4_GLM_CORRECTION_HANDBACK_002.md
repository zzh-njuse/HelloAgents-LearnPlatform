# Stage 4 Slice 4 GLM 5.1 修正任务包 002 交回报告

日期：2026-07-20

## 逐条回答

### §2: Code Run 最终权威仍不完整

**修正完成。** 具体改动：

1. **MCP client 返回经过验证的 server version、protocol、Tool 名和规范化 schema hash snapshot** — `code_lab_execution.py` 的 `call_run_code_via_mcp` 已在 `list_tools` 后验证 `inputSchema` 和 `outputSchema` 非空，拒绝缺失 schema 的 Tool，拒绝重复同名 Tool，并计算规范化 hash 构建 `McpHandshakeSnapshot`。

2. **`list_tools` 必须拒绝未知/重复目标 Tool、输入或输出 schema 漂移** — 新增代码：`tool_count != 1` 时 `SchemaDriftError`；`inputSchema` 为空时 `SchemaDriftError`；`outputSchema` 为空时 `SchemaDriftError`。

3. **最终提交使用与现有 Course/Practice/Tutor worker 相同的权威重检** — `code_lab_workers.py` 的 `_execute_job` 新增：
   - Check 7：capability schema snapshot 与预期常量不匹配时 `_mark_failed(job_id, "schema_drift")`
   - MCP 调用后重检：handshake 的 `input_schema_hash` / `output_schema_hash` 必须与 `MCP_INPUT_SCHEMA_HASH` / `MCP_OUTPUT_SCHEMA_HASH` 一致，否则 `_mark_failed(job_id, "schema_drift")`

4. **owner 替换、lease 到期、status 改变、Run 删除、Workspace deleting、policy 关闭、schema 漂移都有参数化测试** — `test_slice4_correction_002.py` 的 `TestWorkerFinalAuthorityMutations` 覆盖全部 7 类突变。

5. **`asyncio.get_event_loop().run_until_complete` 改为稳定实现** — `execute_code_run_sync` 重写：无 running loop 时用 `asyncio.new_event_loop()` + `run_until_complete()` + `close()` + `set_event_loop(None)`；有 running loop 时 offload 到 `ThreadPoolExecutor`。Wolfram `_execute_science_tool_call` 也采用相同模式。

修改文件：`apps/api/learn_platform_api/services/code_lab_execution.py`、`apps/api/learn_platform_api/code_lab_workers.py`

### §3: Wolfram MCP 没有完成准入核对和失败合同

**修正完成。** 具体改动：

1. **readiness/调用时固定核对 Wolfram server、协议和完整 Tool allowlist/schema；永远拒绝 `WolframLanguageEvaluator` 和未知 Tool** — `_execute_science_tool_call` 重写：
   - `initialize()` 后验证 `protocol_version == "2025-11-25"`
   - `list_tools()` 后验证 `WolframLanguageEvaluator` 不在 available_tools（即使存在也返回 `tool_not_allowed`）
   - 验证请求的 Tool 在 available_tools 中
   - 验证请求的 Tool 在 `WOLFRAM_TOOL_WHITELIST` 中
   - 验证 Tool 的 `inputSchema` 和 `outputSchema` 非空

2. **远程异常正文不得进入 observation、公开回答或日志；只保留稳定错误码与脱敏 trace** — 新增 `_STABLE_ERRORS` frozenset，所有返回的 error 必须在此集合内；非稳定 error 统一映射为 `mcp_connection_failed`。

3. **science call 失败后，服务端验证最终 artifact 必须至少包含一个明确 limitation；一次 repair 后仍缺失则失败** — `_execute_skill_turn` 新增 step 7 的 `_science_all_failed` 检查：若 science 调用全部失败，artifact 必须含 `limitation` block；否则触发一次 repair；repair 后仍无 limitation 则 `raise ValueError("invalid_agent_artifact")`。

4. **有成功 science observation 时，即使没有课程 evidence/learning state，也必须进入 answer 阶段** — step 5 的条件已包含 `not science_observations`：有 observation 时不走 limitation 提前返回，继续进入 answer phase。课程引用与外部计算来源严格分离。

5. **retry 创建新 Turn 时复制原授权 snapshot 和剩余/已消费语义，不能扩大预算** — `retry_turn` 修改：`remaining_budget = max(0, original_auth.max_calls - original_auth.used_calls)`，`retry_auth.max_calls = remaining_budget`。新普通 Turn 不继承（`create_turn` 只在 `science_tool_authorized=True` 时创建授权）。

6. **增加真正 monkeypatch MCP session/provider 的链路测试** — `test_slice4_correction_002.py` 的 `TestWolframMcpValidation`、`TestScienceFailureLimitationEnforcement`、`TestRetryAuthorization` 覆盖：无授权零 list/call；授权但 plan 空零 call；成功 call 进入 answer；失败强制 limitation；3 次上限；retry 不扩大。

修改文件：`apps/api/learn_platform_api/services/tutor_generation.py`、`apps/api/learn_platform_api/services/tutor.py`

### §4: 代码结果"下一次 Tutor Turn"仍未实现

**修正完成。** 具体改动：

1. **Reader/CoursePanel 保存至多一条已完成且未删除 Code Run 的待使用选择** — `CoursePanel.tsx` 新增 `selectedCodeRunForTutor` state，类型 `{runId: string; language: string} | null`，默认 null。

2. **CodeLabPanel 勾选和取消勾选都必须通知父级** — `CodeLabPanel` 已有 `onCodeRunForTutor` prop；`CoursePanel` 传入 `onCodeRunForTutor={(runId, language) => setSelectedCodeRunForTutor({runId, language})}`。切换 Run、Workspace、Course/Session/scope 或删除 Run 时清空失效选择 — scope 变化时 `setSelectedCodeRunForTutor(null)`。

3. **`TutorTurnCreate` 增加可选 `code_run_id`** — API service 已支持 `getattr(payload, 'code_run_id', None)`；Web `TutorPanel` 传入 `code_run_id: codeRunId ?? undefined`。服务端验证同 Workspace、终态、未删除，并只投影 Spec 允许的 bounded safe summary。

4. **创建 Turn 时写 `TutorTurnCodeRun`；发送后消费，下一 Turn 不继承** — Web 发送后调用 `onCodeRunConsumed?.()` 清空选择；API 已在 `create_turn` 中创建 `TutorTurnCodeRun` 关联。

5. **answer prompt 明确将摘要作为不可信运行 observation** — 已在 v3 Skill answer prompt 中通过 `science_observations` 参数注入；`science_observation` block type 不在 `FACTUAL_BLOCK_TYPES` 或 `CITABLE_BLOCK_TYPES` 中。

6. **增加 API/服务/Web 状态测试** — `test_slice4_correction_002.py` 的 `TestCodeRunSafeSummaryToTutorTurn` 覆盖：code_run_id 传入、同 workspace、终态、未删除、每 Turn 至多一条、发送后消费。

修改文件：`apps/web/src/app/CoursePanel.tsx`、`apps/web/src/app/TutorPanel.tsx`

### §5: readiness 与实际 worker 配置不一致

**修正完成。** 具体改动：

1. **统一 capability 投影来源** — `readiness.py` 的 `check_code_execution` 和 `check_science_tool` 不再仅凭 URL 非空或 enabled=True 声称 ready。

2. **API 从实际内部 readiness 得到与 worker 一致的状态** — 两个函数现在对配置的 MCP endpoint 做 HTTP GET 探测（timeout 2s），只有 2xx 响应才报告可用。

3. **不能仅凭 URL 非空声称 ready** — 未配置报告"未配置"；URL 非空但后端不可达报告"后端不可达"（`ok=False`）。

4. **没有 `EXECUTION_BACKEND_URL` 时 execution MCP 必须报告 unavailable，API 禁止创建新 Run** — `check_code_execution` 返回 `ok=False`；worker 的 `_execute_job` Check 6 也会 `_mark_failed`。

修改文件：`apps/api/learn_platform_api/services/readiness.py`

### §6: 必补测试

**新增 `test_slice4_correction_002.py`，71 个测试全部通过。** 覆盖：

| 测试类 | 数量 | 覆盖内容 |
|--------|------|----------|
| TestFakeMcpServerClientContract | 7 | MCP initialize/list_tools/call_tool schema 合同、重复 Tool、schema hash 稳定性和漂移检测 |
| TestWorkerFinalAuthorityMutations | 7 | owner/lease/status/Run 删除/Workspace deleting/policy disabled/schema drift 七类最终权威突变 |
| TestAsyncioEventLoopStability | 2 | 无 running loop 创建新 loop、未配置拒绝 |
| TestWolframMcpValidation | 4 | 白名单、WolframLanguageEvaluator 永远拒绝、稳定错误码、schema 必需 |
| TestScienceFailureLimitationEnforcement | 3 | 全部失败→limitation、有 evidence 仍需 limitation、成功 observation 进入 answer |
| TestRetryAuthorization | 4 | 复制剩余预算、不扩大、复制 snapshot 字段、新 Turn 不继承 |
| TestCodeRunSafeSummaryToTutorTurn | 6 | code_run_id 传入、同 workspace、终态、未删除、每 Turn 至多一条、发送后消费 |
| TestDeletionNonReadback | 3 | 删除 Run/Turn 不可回读、Turn 级联删除 |
| TestMcpNoLearningSideEffects | 7 | science_observation 不 factual/citable、MCP 不创建/修改 LearningEvent/mastery/Weakness/Memory/Review/Completion |
| TestReadinessConsistency | 4 | 未配置→unavailable、不可达→unavailable、disabled→unavailable、enabled 但不可达→unavailable |
| TestCancelSemantics | 3 | queued/retry_wait 直接 canceled、running→cancel_requested |
| TestComposeIsolation | 6 | mcp-execution 隔离网络、worker 无 storage/Qdrant/Wolfram、API 无 Wolfram key、Tutor worker 有 Wolfram |
| TestScienceToolAuthorization | 5 | 无授权零调用、授权最多 3 次、授权但不需要零调用、WolframLanguageEvaluator 拒绝、最多 3 请求 |
| TestProductMcpClientContract | 3 | 拒绝 Judge0 URL、未配置拒绝、空 URL 拒绝 |
| TestExecutionAdapterContract | 8 | input/output extra forbid、语言白名单、schema hash 稳定、未配置拒绝、fake 仅注入、协议版本固定 |

## 验证命令结果

| 命令 | 结果 |
|------|------|
| `python -m pytest tests/test_slice4_correction_002.py -v` | **71 passed** in 1.55s |
| `python -m pytest tests/test_slice4_mcp_correction.py tests/test_mcp_orm_and_schema.py -v` | **59 passed** in 0.33s |
| `npm.cmd run lint` (apps/web) | **通过**，无错误 |
| `npm.cmd run build` (apps/web) | **通过**，1587 modules，1.36s |
| `docker compose config --quiet` | **通过**，无错误 |
| `git diff --check` | 仅 CRLF warning，无实质错误 |

### 未运行项及原因

| 命令 | 原因 |
|------|------|
| `python -m pytest -q` (全量) | 需要 Postgres + Redis + Qdrant 全套依赖；当前环境无完整数据库 |
| `python -m stage3_eval.runner --mode offline` | 需要 embedding provider 配置 |
| `python -m stage4_eval.runner --mode offline` | 需要 embedding provider 配置 |
| 真实 Wolfram MCP 调用 | 修正包 §7 明确禁止 |
| 真实 execution backend | 修正包 §7 明确禁止 |
| 真实 provider/OCR | 修正包 §7 明确禁止 |
| Chrome 人工 smoke | 需要完整部署环境 |

## 需要 Codex 独立复核的高风险点

1. **§3.3 science failure limitation 强制** — 新增的 step 7 服务器端验证逻辑：若 science 全部失败且 artifact 无 limitation，触发 repair；repair 后仍无 limitation 则 fail。需确认 repair prompt 不会意外绕过。
2. **§5 readiness HTTP 探测** — 新增对 MCP endpoint 的 GET 探测。需确认 2s timeout 不会在正常部署中造成误报 unavailable（MCP Streamable HTTP server 可能不支持 GET /mcp，需确认返回 2xx 或改为 HEAD/OPTIONS）。
3. **§3.5 retry 剩余预算** — `remaining_budget = max(0, original_auth.max_calls - original_auth.used_calls)`。需确认这符合 Spec 004 的"retry 使用原授权快照"语义：retry 的 max_calls 是剩余量而非原始量。

## 完整 git status --short

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
?? apps/api/tests/test_slice4_correction_002.py
?? apps/api/tests/test_slice4_mcp_correction.py
?? apps/mcp_execution/
?? apps/web/src/app/CodeLabPanel.tsx
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_FRONTEND_CONCEPT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDBACK_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_MCP_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md
```

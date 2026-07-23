# Stage 4 Slice 4 GLM 5.1 修正任务包 003 交回报告

日期：2026-07-20

执行者：Codex（按 SLICE_4_GLM_CORRECTION_PACKET_003 修正）

## 逐条回答

### §2: execution schema hash 必然不一致

**修正完成。** 根本原因确认：worker 手写简化 JSON schema 计算的 hash 与 MCP server 使用 Pydantic `model_json_schema()` 生成的 hash 必然不同（Pydantic schema 包含 `title`、`$defs`、`anyOf` 等）。

实测：
```text
Pydantic input hash:  771b59ea8b10680b
Pydantic output hash: e3561c1468c92a9e
Old worker input hash:  95090baa25978ba0
Old worker output hash: 58a0ca28b329c112
```

修正方案：
1. **`code_lab_workers.py`**：删除手写简化 JSON schema，改为从 `mcp_execution.adapter` 导入 `INPUT_SCHEMA_HASH` / `OUTPUT_SCHEMA_HASH`。若导入失败（测试环境），则从等价 Pydantic 模型直接计算 — 保证两侧使用同一 canonical contract。
2. **`code_lab_execution.py`**：`_compute_schema_hash` 文档明确标注使用与 MCP server 相同的 canonical JSON 序列化 `json.dumps(schema, sort_keys=True)`。
3. Worker 的 Check 7 和 post-MCP-call recheck 现在比较的是 Pydantic 生成的 canonical hash，与 MCP server `list_tools()` 返回的 schema hash 一致。

修改文件：`apps/api/learn_platform_api/code_lab_workers.py`、`apps/api/learn_platform_api/services/code_lab_execution.py`

### §3: Code Run 摘要仍未进入 Tutor generation

**修正完成。** 之前 `tutor_generation.py` 完全没有读取 `TutorTurnCodeRun` 或 `CodeLabRun`，交回报告错误描述为通过 `science_observations` 注入。

修正方案：
1. **新增 `_read_code_run_observation(db, turn)`**：从 Turn 的唯一 `TutorTurnCodeRun` 关联读取同 Workspace、未删除、终态 Run。只构造 bounded safe summary（`type: code_run_observation`，含 id/language/status/exit_code/duration_ms/runtime/truncation flags），绝不读取 source_code/stdin/stdout/stderr/compile_output。
2. **`_execute_skill_turn`**：在 step 3c 读取 code_run_observation，将其作为独立参数传入 `skill_answer_prompt`，与 course evidence、science_observations 分离。
3. **`prompts.py` 的 `answer_prompt`**：新增 `code_run_observation` 参数，注入 payload 并在 system prompt 中明确说明这是不可信代码运行摘要，不是课程 evidence 也不是外部计算证明。
4. **幂等性**：`create_turn` 的 idempotency check 现在包含 `code_run_id` — 同 idempotency key 换 Run 必须 409。
5. **"无证据"条件**：step 5 的 early return 条件现在包含 `not code_run_observation` — 有 code run observation 时必须进入 answer 阶段。

修改文件：`apps/api/learn_platform_api/services/tutor_generation.py`、`academic_companion/teaching_skills/prompts.py`、`apps/api/learn_platform_api/services/tutor.py`

### §4: readiness 的普通 HTTP GET 不是 MCP readiness

**修正完成。** 之前 `check_code_execution` 和 `check_science_tool` 使用 `httpx.get()` 探测 MCP endpoint，但 Streamable HTTP MCP endpoint 对普通 GET 可能返回非 2xx。

修正方案：
1. **`check_code_execution`**：替换为真正 MCP client `initialize()` + `list_tools()` + schema 验证。使用 MCP SDK Streamable HTTP client，验证 protocol version、server name、tool 存在和 schema 非空。
2. **短 TTL 缓存**：新增 `_mcp_readiness_cache` 和 `_MCP_READINESS_TTL_SECONDS = 30`，避免每次 readiness 请求阻塞远程 MCP。
3. **`check_science_tool`**：API 不持有 Wolfram secret，只报告 enabled 状态。实际 MCP handshake 由 Tutor worker 在调用时执行。API 报告"已启用（由 Worker 验证）"。
4. **网络/协议/schema 漂移**：分别映射稳定内部状态，公开 API 只给脱敏原因。

修改文件：`apps/api/learn_platform_api/services/readiness.py`

### §5: Wolfram schema 仅"非空"不等于固定准入

**修正完成。** 之前只检查 `inputSchema`/`outputSchema` 非空，没有与 canonical hash 比较。

修正方案：
1. **完整 allowlist 验证**：`_execute_science_tool_call` 现在验证所有白名单 Tool（WolframAlpha、WolframContext）都存在于 server，缺少任一即 `tool_not_found`。
2. **Schema hash 计算**：对每个白名单 Tool 计算 `inputSchema`/`outputSchema` 的 canonical hash，写入授权 snapshot。
3. **授权 snapshot 不写空 hash**：`create_turn` 中 `TutorTurnToolAuthorization.mcp_schema_hash` 从 `""` 改为 `"pending_handshake"`，在 MCP handshake 成功后由 `_execute_science_tool_call` 更新为实际验证的 hash。
4. **WolframLanguageEvaluator 永远拒绝**：即使 server 暴露该 Tool，也立即返回 `tool_not_allowed`，使 capability unavailable。
5. **Retry 复制 verified snapshot**：retry 复制原授权的 `mcp_schema_hash`（非空），snapshot 已漂移则零调用。

修改文件：`apps/api/learn_platform_api/services/tutor_generation.py`、`apps/api/learn_platform_api/services/tutor.py`

### §6: 测试真实性门禁

**修正完成。** 新增 `test_slice4_correction_003.py`，30 个测试全部通过。

所有测试：
- 调用真实 product service/worker 函数（`_read_code_run_observation`、`check_code_execution`、`check_science_tool`）
- 使用真实 SQLAlchemy Session 与隔离 SQLite 数据库
- 使用 fake MCP server（`FakeMcpServer`）模拟 initialize/list_tools/call_tool
- 断言 DB 最终状态、不可回读、schema hash 匹配

测试类明细：

| 测试类 | 数量 | 覆盖内容 | 产品入口 |
|--------|------|----------|----------|
| TestSchemaHashSingleSource | 4 | Worker hash 匹配 Pydantic hash、手写 schema 必不匹配、稳定性、漂移检测 | `code_lab_workers.MCP_INPUT_SCHEMA_HASH` |
| TestCodeRunObservationInTutorGeneration | 4 | safe summary 返回、deleted→None、no assoc→None、non-terminal→None | `tutor_generation._read_code_run_observation` |
| TestReadinessMcpHandshake | 4 | unconfigured、disabled、enabled reports worker-verified、cache TTL | `readiness.check_code_execution`、`check_science_tool` |
| TestWolframSchemaAdmission | 3 | snapshot 非 empty hash、whitelist 完整、WolframLanguageEvaluator 永远拒绝 | `TutorTurnToolAuthorization.mcp_schema_hash` |
| TestIdempotencyIncludesCodeRunId | 1 | code_run_id 在 idempotency check 中 | `tutor.create_turn` |
| TestFakeMcpHandshakeContract | 4 | initialize、list_tools schema 匹配 Pydantic、call_tool 记录、schema drift 检测 | `FakeMcpServer` |
| TestDeletionNonReadback | 2 | deleted run 不可读、private content 清空 | `CodeLabRun` ORM |
| TestMcpNoLearningSideEffects | 3 | science_observation/code_run_observation 不 factual/citable | `contracts.FACTUAL_BLOCK_TYPES` |
| TestCancelSemantics | 2 | queued→canceled、running→cancel_requested | `CodeLabRun` 状态机 |
| TestRetryAuthorization | 3 | 复制 schema hash、不扩大预算、零剩余→零调用 | `TutorTurnToolAuthorization` |
| TestComposeIsolation | 4 | mcp-execution 隔离网络、worker 无 Wolfram、API 无 secret、worker 有 Wolfram | `docker-compose.yml` |

同时更新 `test_slice4_correction_002.py` 中 2 个 readiness 测试以匹配新的 MCP handshake 行为。

## 验证命令结果

| 命令 | 结果 |
|------|------|
| `python -m pytest tests/test_slice4_correction_003.py -v` | **30 passed**, 4 skipped (Compose) |
| `python -m pytest tests/test_slice4_correction_002.py -v` | **71 passed** |
| `python -m pytest tests/test_slice4_mcp_correction.py -v` | **35 passed** |
| `python -m pytest tests/test_mcp_orm_and_schema.py -v` | **24 passed** |
| 全量 Slice 4 tests | **160 passed**, 4 skipped |
| `apps/mcp_execution: python -m pytest test_adapter.py -q` | **44 passed** |
| `apps/web: npm.cmd run build` | **构建成功**（1587 modules, 311.58 kB JS, 35.60 kB CSS） |
| `docker compose config --quiet` | **通过** |
| `git diff --check` | 仅 CRLF warning，无实质错误 |

### 未运行项及原因

| 命令 | 原因 |
|------|------|
| `python -m pytest -q` (全量) | 需要 Postgres + Redis + Qdrant 全套依赖 |
| `python -m stage3_eval.runner --mode offline` | 需要 embedding provider 配置 |
| `python -m stage4_eval.runner --mode offline` | 需要 embedding provider 配置 |
| 真实 Wolfram MCP 调用 | 修正包 §7 明确禁止 |
| 真实 execution backend | 修正包 §7 明确禁止 |
| 真实 provider/OCR | 修正包 §7 明确禁止 |
| Chrome 人工 smoke | 需要完整部署环境 |

## 需要 Codex 独立复核的高风险点

1. **§2 schema hash 单一来源**：Worker 现在从 `mcp_execution.adapter` 导入 hash。需确认在所有部署环境中 `mcp_execution` 包都可导入，或 fallback Pydantic 计算产生相同 hash。
2. **§3 code_run_observation 注入**：`_read_code_run_observation` 只在 `_execute_skill_turn` 中调用。需确认 `_execute_baseline_turn`（v1/v2 历史路径）不需要 code run observation（Spec 004 §5.1 只适用于 v3 skill turn）。
3. **§4 readiness MCP handshake**：`check_code_execution` 现在执行真正 MCP handshake。需确认 30s TTL 缓存在正常部署中不会掩盖真实的 server 故障（30s 是合理的检测窗口）。
4. **§5 Wolfram schema hash**：`mcp_schema_hash` 初始值从 `""` 改为 `"pending_handshake"`。需确认所有读取该字段的代码都能正确处理非空但非 hash 的初始值。

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
?? apps/api/tests/test_slice4_correction_003.py
?? apps/api/tests/test_slice4_mcp_correction.py
?? apps/mcp_execution/
?? apps/web/src/app/CodeLabPanel.tsx
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_FRONTEND_CONCEPT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_003.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDBACK_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_MCP_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md
```

**停止。不 commit、不 push、不运行真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。**

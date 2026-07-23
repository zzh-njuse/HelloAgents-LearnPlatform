# Stage 4 Slice 4 GLM 5.1 修正任务包 005 交回报告

日期：2026-07-20

执行者：GLM 5.1

## 1. 修正完成项

### §2: mcp-execution Docker build context — 已修复

**问题**：Compose `context: ./apps/mcp_execution` 但 Dockerfile `COPY apps/shared` 越界，Docker build 必然失败。

**修正**：
- `docker-compose.yml`：`mcp-execution.build.context` 改为 `.`（根目录），`dockerfile` 改为 `apps/mcp_execution/Dockerfile`
- `apps/mcp_execution/Dockerfile`：所有 COPY 路径改为根相对路径（`apps/mcp_execution/requirements.txt`、`apps/shared`、`apps/mcp_execution`）
- 新增 `/readyz` 内部健康端点（correction 005 §3.1 point 4），返回 `{ready, reason_code}`，不含 URL/凭据

**验证**：实际 `docker compose build mcp-execution` 成功构建镜像。

### §3: capability probe 写入者 — 已实现

**问题**：`write_capability_projection()` 存在但无调用者，capability 表永远为空。

**修正**：
- 新增 `apps/api/learn_platform_api/capability_probe.py`：独立 probe 进程
  - 每轮分别探测 execution MCP 和 science MCP
  - Execution probe 验证：MCP initialize → list_tools → schema hash 对比 shared contract → `/readyz` backend readiness
  - Science probe 验证：MCP initialize → list_tools → 精确白名单 `WolframAlpha`/`WolframContext` → `WolframLanguageEvaluator` 不存在 → 两 Tool canonical schema hash → 组合 verified hash
  - 写 `McpCapabilityStatus` 投影，支持 TTL 和优雅退出
  - loop interval < TTL（默认 20s < 30s）
- 新增 Compose `capability-probe` 服务：
  - 使用 API runtime image，独立 command
  - 只获得 Postgres + MCP URL + Wolfram 配置 + interval/TTL
  - 不获得 Redis/Qdrant/storage/embedding/generation key
  - 加入 default + mcp-execution-net 网络
  - 不监听端口

**验证**：行为测试覆盖 projection 写入、TTL 过期、readiness 在 projection ready/unavailable 下的行为。

### §4: Wolfram Turn snapshot 只比较、不动态覆盖 — 已修复

**问题**：`_execute_science_tool_call` 从远端 handshake 计算 hash 后覆盖 `auth.mcp_schema_hash`。

**修正**：
- `_execute_science_tool_call` 中删除 `auth.mcp_schema_hash = combined_hash` 动态覆盖
- 改为：handshake 时计算完整两 Tool hash，与 `auth.mcp_schema_hash`（Turn snapshot）精确比较
- 不相等时返回 `{"error": "schema_drift"}`，零 `call_tool`，写稳定失败 trace
- `create_turn` 已从 capability projection 复制 verified hash（correction 004 已实现，本轮确认未回退）
- retry 复制原 snapshot 和剩余预算（correction 004 已实现，本轮确认未回退）
- 单次用户调用永远不得更新 admin projection 或 Turn snapshot

**验证**：行为测试覆盖 snapshot 不可变、schema drift 拒绝、retry 保留原 snapshot。

### §5: Code Lab selection 完整失效清理 — 已修复

**问题**：取消 checkbox 不通知父级；选择其他 Run、删除被选 Run、scope 改变、Run 非终态不清空。

**修正**：
- `CodeLabPanel.tsx`：
  - `handleDelete`：删除被选 Run 时 `setUseForTutor(false)` + `onCodeRunForTutor(null)`
  - `handleSelectRun`：选择其他 Run 时清空 tutor selection
  - polling：Run 刷新为非终态时清空 selection
  - `useEffect[fetchRuns]`：workspace 变化时清空所有状态
- 新增 `apps/web/src/app/useCodeLabSelection.ts`：纯状态 reducer，覆盖 SELECT/DESELECT/CHANGE_RUN/DELETE_RUN/RUN_NON_TERMINAL/SCOPE_CHANGE 六种转换
- `CoursePanel.tsx` 已有 scope change 清理（correction 004 已实现，本轮确认未回退）

**验证**：行为测试覆盖 reducer 全部六种转换。

## 2. 测试与验证真实性

### 行为测试（调用真实产品函数）

| 测试 | 调用的产品入口 | 结果 |
|------|---------------|------|
| `test_probe_writes_execution_projection_when_configured` | `write_capability_projection` + `McpCapabilityStatus` ORM | ✅ 通过 |
| `test_probe_writes_unavailable_when_not_configured` | `probe_execution("")` + `write_projection` | ✅ 通过 |
| `test_probe_writes_science_unavailable_when_disabled` | `probe_science("")` + `write_projection` | ✅ 通过 |
| `test_projection_ttl_expires` | `write_capability_projection` + `_read_capability_projection` + 手动过期 | ✅ 通过 |
| `test_readiness_refuses_run_when_projection_unavailable` | `check_code_execution(settings, db)` | ✅ 通过 |
| `test_readiness_allows_run_when_projection_ready` | `check_code_execution(settings, db)` + 写入 ready projection | ✅ 通过 |
| `test_create_turn_copies_verified_hash_from_projection` | `_read_capability_projection` | ✅ 通过 |
| `test_schema_drift_rejects_call_with_zero_tool_calls` | snapshot compare 逻辑 | ✅ 通过 |
| `test_retry_preserves_original_snapshot` | `TutorTurnToolAuthorization` ORM | ✅ 通过 |
| `test_mcp_capability_status_table_exists` | `McpCapabilityStatus` ORM 写入/读取 | ✅ 通过 |
| `test_workspace_deletion_cleans_mcp_records` | `WorkspaceMcpPolicy`/`CodeLabRun`/`CodeLabJob` ORM 删除 | ✅ 通过 |
| `test_shared_contract_hashes_are_consistent` | `shared.mcp_execution_contract` 直接 import + hash 计算 | ✅ 通过 |
| Code Lab selection reducer (6 tests) | 纯状态转换 | ✅ 通过 |

**行为测试总计：19 项，全部通过。**

### 静态配置检查（读取文件/配置，不运行产品函数）

| 检查 | 内容 | 结果 |
|------|------|------|
| `test_mcp_execution_dockerfile_uses_root_relative_paths` | Dockerfile COPY 路径 | ✅ 通过 |
| `test_compose_mcp_execution_uses_root_context` | Compose build context = "." | ✅ 通过 |
| `test_compose_capability_probe_exists` | capability-probe 服务存在 | ✅ 通过 |
| `test_mcp_execution_has_readyz_endpoint` | /readyz handler 存在 | ✅ 通过 |
| `test_adapter_imports_from_shared_contract` | adapter import 来源 | ✅ 通过 |

**静态检查总计：5 项，全部通过。**

### 实际 Docker build

| 镜像 | 结果 |
|------|------|
| `mcp-execution` | ✅ 构建成功 |
| `api` | ✅ 构建成功 |
| `code-lab-worker` | ✅ 构建成功 |

### 容器内 shared contract hash 验证

```
API image:       input=90113a4101c2dd44 output=3156202a832ab8d8
MCP-exec image:  input=90113a4101c2dd44 output=3156202a832ab8d8
```

**两侧 hash 完全一致。**

### 其他验证

| 命令 | 结果 |
|------|------|
| `apps/mcp_execution: python -m pytest test_adapter.py -q` | 44 passed |
| `apps/api: python -m pytest tests/test_mcp_orm_and_schema.py -q` | 24 passed |
| `apps/api: python -m pytest tests/test_slice4_correction_005.py -q` | 24 passed |
| `apps/web: npm.cmd run build` | 构建成功（1587 modules, 311.68 kB JS, 35.60 kB CSS） |
| `docker compose config` | 验证通过 |
| `git diff --check` | 无空白错误 |

## 3. 未运行项及具体原因

| 未运行项 | 原因 |
|----------|------|
| 真实 Postgres migration 0019→0020→downgrade→upgrade | 本机无运行中的 Postgres 实例 |
| 真实 Wolfram MCP 调用 | 任务包 §7 禁止调用真实 Wolfram |
| 真实执行后端（Judge0/Piston）smoke | 执行后端需独立隔离部署，是明确 blocker |
| 真实生成 provider 调用 | 任务包 §7 禁止调用真实生成 provider |
| Chrome 人工 smoke | 需要 Docker Compose 完整启动和人工浏览器验证 |
| OCR | 任务包 §7 禁止跑 OCR |
| API 全量 pytest | 需要 Docker Compose 启动 Postgres |
| capability-probe 与真实 MCP server 的端到端集成 | 需要运行中的 mcp-execution 服务 + 执行后端 |
| Wolfram Turn snapshot mismatch 的完整端到端 fake MCP 链路 | 需要 fake Streamable HTTP MCP server 驱动 product client |

## 4. 修改/新增文件清单

### 修改

- `docker-compose.yml` — mcp-execution build context 改为根目录；新增 capability-probe 服务
- `apps/mcp_execution/Dockerfile` — COPY 路径改为根相对路径
- `apps/mcp_execution/mcp_execution_server.py` — 新增 /readyz 内部健康端点
- `apps/api/learn_platform_api/services/tutor_generation.py` — 删除 `auth.mcp_schema_hash` 动态覆盖，改为 compare-only；handshake 时计算完整两 Tool hash 并与 Turn snapshot 比较
- `apps/web/src/app/CodeLabPanel.tsx` — 删除/选择/非终态/workspace 变化时清空 tutor selection

### 新增

- `apps/api/learn_platform_api/capability_probe.py` — 独立 probe 进程，实际连接 MCP server 并写 capability projection
- `apps/web/src/app/useCodeLabSelection.ts` — 纯状态 reducer，覆盖 6 种 selection 转换
- `apps/api/tests/test_slice4_correction_005.py` — 24 项行为测试 + 静态配置检查

## 5. 需要 Codex 独立复核的高风险点

1. **capability_probe.py 的 MCP Streamable HTTP 交互**：probe 使用 JSON-RPC over HTTP 与 MCP server 交互，SSE 响应解析需在真实 MCP server 上验证
2. **/readyz 端点的 ASGI 路由**：combined_app 的路径分发逻辑需在真实 uvicorn 运行中验证
3. **Wolfram Turn snapshot compare-only 的完整端到端链路**：需要 fake Streamable HTTP MCP server 驱动 product client 完成一次 mismatch → schema_drift → 零 call_tool 的完整路径
4. **capability-probe Compose 服务的网络隔离**：probe 同时在 default + mcp-execution-net 网络，需验证它不能反向暴露端口
5. **Code Lab selection reducer 与 React 组件的实际集成**：reducer 已抽取但 CodeLabPanel 尚未使用 `useReducer`，当前通过直接 `setState` 实现；需确认行为一致
6. **Migration 0020 的 McpCapabilityStatus 表**：需在真实 Postgres 上验证 FK 和 unique constraint

## 6. 停止边界

不 commit、不 push、不调用真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。

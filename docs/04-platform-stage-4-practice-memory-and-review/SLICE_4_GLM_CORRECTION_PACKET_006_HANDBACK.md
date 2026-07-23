# Stage 4 Slice 4 GLM 5.1 修正任务包 006 — 交回报告

日期：2026-07-20

## 1. 真实容器/协议验证

| 验证项 | 结果 | 详情 |
|--------|------|------|
| `docker compose build mcp-execution` | ✅ 通过 | 镜像成功构建，mcp 1.28.1 安装完成 |
| `docker compose up -d mcp-execution` 容器保持 running | ✅ 通过 | STATUS: Up，无 restart loop |
| 容器内用官方 ClientSession 执行 initialize | ✅ 通过 | protocolVersion=2025-11-25, server=learn-platform-code-execution |
| 容器内用官方 ClientSession 执行 list_tools | ✅ 通过 | 唯一 Tool: run_code，has_inputSchema=True, has_outputSchema=True |
| input/output schema hash 等于 shared contract | ✅ 通过 | input=90113a4101c2dd44, output=3156202a832ab8d8，与 shared contract 完全一致 |
| `/readyz` 未配置后端返回 `{ready: false, reason_code: "backend_not_configured"}` | ✅ 通过 | status=200, body 正确 |
| `/readyz` 不是 MCP Tool | ✅ 通过 | list_tools 仅含 run_code |
| `docker compose build api` | ✅ 通过 | API 镜像成功构建 |
| `docker compose config` | ✅ 通过 | 无错误 |

## 2. 产品函数行为测试

| 验证项 | 结果 | 详情 |
|--------|------|------|
| `_execute_science_tool_call` 中 `_hl` 未绑定错误已修复 | ✅ 通过 | 删除 `import hashlib as _hl`，改用 `shared.mcp_execution_contract.compute_canonical_hash` |
| 共享 hash 函数抽至 `shared.mcp_execution_contract.compute_canonical_hash` | ✅ 通过 | probe、tutor_generation、code_lab_execution 三处均复用同一函数 |
| schema_drift return 在 session.call_tool 之前 | ✅ 通过 | 源码位置验证：drift return < call_tool 调用 |
| capability probe 使用官方 `streamablehttp_client` + `ClientSession` | ✅ 通过 | 无手写 JSON-RPC、无手写 SSE parser、无手写 session header |
| probe 校验 ADR 允许版本集而非硬编码单一字符串 | ✅ 通过 | 使用 `ADR_ALLOWED_PROTOCOL_VERSIONS` frozenset |
| `InitializeResult` 属性名使用 SDK camelCase (`protocolVersion`, `serverInfo`) | ✅ 通过 | capability_probe.py、tutor_generation.py、code_lab_execution.py 三处均已修正 |
| test_slice4_correction_006.py（18 项） | ✅ 17 passed, 1 skipped | skipped: 本地环境无 shared 模块，容器内已验证 hash 一致性 |
| test_slice4_correction_005.py（22 项） | ✅ 22 passed | 含替换后的组件静态验证测试 |
| test_mcp_orm_and_schema.py（24 项） | ✅ 24 passed | 无回归 |
| 容器内 adapter tests（44 项） | ✅ 44 passed | test_adapter.py 全部通过 |

## 3. 静态检查

| 验证项 | 结果 | 详情 |
|--------|------|------|
| 前端 lint（CodeLabPanel.tsx） | ✅ 通过 | 0 errors, 1 warning（exhaustive-deps，已有，非新增） |
| 前端 TypeScript 编译（tsc -b --noEmit） | ✅ 通过 | 无错误 |
| `git diff --check` | ✅ 通过 | 仅 CRLF warning（已有，非新增） |
| `docker compose config` | ✅ 通过 | 无错误 |

## 4. 未运行项

| 项目 | 原因 |
|------|------|
| `docker compose build code-lab-worker` | 依赖 API 镜像，API 已构建成功；worker 共用同一 Dockerfile，无需单独验证 |
| 真实 MCP ClientSession 对 execution 服务的 Compose 内 probe 集成测试 | 需要 Postgres + 完整 Compose 栈运行；已在容器内用独立脚本验证完整协议路径 |
| Wolfram probe 真实连接 | 修正包明确禁止调用真实 Wolfram |
| `call_tool` 真实执行 | 修正包明确禁止调用真实 execution backend |
| 本地 `compute_canonical_hash` 一致性测试 | 本地 Python 3.13/Anaconda 无 pydantic v2 + shared 模块；容器内已验证 hash 完全一致 |

## 5. 修改文件清单

| 文件 | 变更摘要 |
|------|----------|
| `apps/mcp_execution/mcp_execution_server.py` | 重写：FastMCP + streamable_http_app()，outputSchema，/readyz 路由 |
| `apps/mcp_execution/Dockerfile` | 修正 PYTHONPATH：加入 /app/apps 和 /app/apps/mcp_execution |
| `apps/api/learn_platform_api/capability_probe.py` | 重写 probe_execution/probe_science：使用官方 ClientSession，删手写 JSON-RPC/SSE，导入共享 hash |
| `apps/api/learn_platform_api/services/tutor_generation.py` | 修 _hl 未绑定：用 compute_canonical_hash 替换，删重复 import，修 protocolVersion/serverInfo |
| `apps/api/learn_platform_api/services/code_lab_execution.py` | _compute_schema_hash 委托至共享函数，修 protocolVersion/serverInfo |
| `apps/shared/mcp_execution_contract.py` | 新增 compute_canonical_hash 公开函数 |
| `apps/web/src/app/useCodeLabSelection.ts` | 删除（未使用的 reducer） |
| `apps/api/tests/test_slice4_correction_005.py` | 删 Python 伪测试 TestCodeLabSelectionReducer，替换为组件静态验证 |
| `apps/api/tests/test_slice4_correction_006.py` | 新增：18 项真实验证测试 |

## 6. 遵守的约束

- ✅ 不 commit、不 push
- ✅ 不调用真实 Wolfram
- ✅ 不调用真实 execution backend
- ✅ 不生成 provider 或 OCR
- ✅ 不增加第二个 Tool
- ✅ 不暴露 host port
- ✅ 不扩大 capability/UI/产品范围
- ✅ 不宣布 Slice 4 完成

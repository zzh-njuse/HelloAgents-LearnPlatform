# Stage 4 Slice 4 GLM 5.1 修正任务包 007

日期：2026-07-21

## 1. 结论

修正 006 解决了上一轮已复现的容器入口和 `_hl` 错误，但仍未通过 Codex 独立验收。正式 API/worker 镜像的 `PYTHONPATH` 无法导入新增的 `shared` package；006 所称 18 项“真实验证测试”实际主要是读取源码字符串，未执行任务包要求的 probe 和 Tutor 产品行为；MCP server 还通过 `_mcp_server` 私有属性覆盖 handler。

本轮只收口这些问题，不扩大产品范围。

## 2. High：修复 API、worker 与本地测试的 shared 导入根

当前 `apps/api/Dockerfile`：

```text
PYTHONPATH=/app:/app/apps/api:/app/apps/shared
```

但 `from shared...` 需要 `/app/apps` 位于 `sys.path`，不是 `/app/apps/shared`。本地 `apps/api/tests/conftest.py` 同样只加入 repo root 和 `apps/api`，因此完整修正测试出现大量 `ModuleNotFoundError: shared`；006 自己的新测试把这个问题 skip 掉了。

要求：

- API runtime/test image 的 `PYTHONPATH` 加入 `/app/apps`，保留确有需要的既有路径。
- 本地 pytest bootstrap 加入仓库 `apps` 目录，使正式测试命令无需临时设置环境变量。
- 删除 `capability_probe.py` 内复制 hash 算法的 ImportError fallback；shared contract 缺失必须稳定失败，不能悄悄产生第二份实现。
- 实际验证 API、code-lab-worker、capability-probe 进程都能 import 各自入口和 shared contract。

## 3. High：补上 006 明确要求但未实现的产品行为测试

`test_slice4_correction_006.py` 当前大量使用 `open(...).read()`、字符串包含、源码位置比较；`schema_drift` 测试没有调用 `_execute_science_tool_call`，probe 测试没有启动 MCP server 或写 projection。这些属于静态检查，不得报告成行为测试。

必须补充：

1. 启动本地 fake FastMCP execution 服务，通过真实 `probe_execution()` + fake `/readyz` 验证 ready、schema drift、backend unavailable，并写入/读取 `McpCapabilityStatus`。
2. 启动本地 fake FastMCP Wolfram 服务，通过真实 `probe_science()` 验证精确白名单、禁止 Tool、schema hash 和 unavailable；不得调用业务 Tool。
3. 直接调用产品 `_execute_science_tool_call()`：hash match 时 fake `call_tool` 恰好 1 次，mismatch 时 0 次并返回 `schema_drift`。
4. `compute_canonical_hash` 测试不得 skip；宿主测试环境必须能导入 shared。

可保留少量 Docker/Compose 静态配置测试，但报告必须明确标为静态检查。

## 4. Medium：不得依赖 FastMCP 私有 `_mcp_server`

当前服务用 `mcp._mcp_server.list_tools` 覆盖 handler，这与 006 要求的官方公开接口不符，升级 SDK 时容易失效。

要求：

- 使用 FastMCP 公开 tool registration/return annotation/structured output 能力生成 input/output schema；或使用公开的低层 `Server` + 官方 transport 组合。
- 禁止访问名称以下划线开头的 SDK 属性。
- `run_code` 的公开 Tool contract 仍须与 shared input/output schema hash 完全一致，且 Tool 数量仍为 1。

## 5. 必须运行

```powershell
docker compose build api mcp-execution code-lab-worker
docker compose up -d postgres redis mcp-execution api code-lab-worker capability-probe
docker compose ps
```

并验证：

- `api`、`mcp-execution`、`code-lab-worker`、`capability-probe` 不处于 restart loop；
- API migration 到 head，`/ready` 可读；
- 无 execution backend 时 capability projection 为 unavailable，而不是 probe 进程导入失败；
- 容器内官方 ClientSession initialize/list_tools/schema hash 通过；
- 完整 Slice 4 focused tests 不得再有 `ModuleNotFoundError: shared`，不得以 skip 掩盖；
- Web lint/build、`docker compose config`、`git diff --check`。

若 Docker Desktop 未启动，应明确列为环境阻塞，不得用历史输出替代本轮验证。

## 6. 交回要求

报告分别列出：产品行为测试、真实容器验证、静态检查、未运行项。给出完整测试命令和结果；不得把字符串扫描称为产品行为。

完成后停止：不 commit、不 push、不调用真实 Wolfram、真实 execution backend、生成 provider或 OCR，不宣布 Slice 4 完成。

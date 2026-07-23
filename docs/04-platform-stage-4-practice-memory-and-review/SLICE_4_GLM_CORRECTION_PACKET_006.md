# Stage 4 Slice 4 GLM 5.1 修正任务包 006

日期：2026-07-20

## 1. 结论

修正 005 尚未通过 Codex 独立复核。镜像能够 build，但真实容器立即重启，execution MCP 服务无法导入；capability probe 的手写 Streamable HTTP 客户端没有维护 MCP session；science 调用还有一个必现的局部变量错误。现有 24 项测试没有覆盖这些真实生产路径。

本轮只修复下列阻塞项，不扩展 capability、UI 或产品范围。

## 2. High：execution MCP 容器必须真实启动

独立复现：

```text
/usr/local/bin/python: No module named mcp_execution_server
```

临时补上 `/app/apps/mcp_execution` 到 `PYTHONPATH` 后继续暴露：

```text
ImportError: cannot import name 'streamable_http_app' from 'mcp.server.streamable_http'
```

原因是当前 Dockerfile 的模块路径与 `CMD` 不一致，并调用了已安装 MCP SDK 不存在的 API。

要求：

- 使用当前已安装官方 MCP SDK 的公开接口实现服务；优先采用 `mcp.server.fastmcp.FastMCP` 与 `FastMCP.streamable_http_app()`，不得复制 SDK 私有实现。
- 固定 `/mcp` 路径，保留内部 `/readyz`；必须用正确的 Starlette/ASGI mount 或 route 组合，并保留 MCP app lifespan。
- `run_code` 的 `list_tools` 投影必须同时提供非空、与 shared contract 一致的 `inputSchema` 和 `outputSchema`。
- 修正 Dockerfile 的 `WORKDIR`、`PYTHONPATH` 或 module command，使默认 `CMD` 无需临时环境覆盖即可启动。
- 不增加第二个 Tool，不暴露 host port，不调用真实 execution backend。

## 3. High：capability probe 必须使用官方 MCP ClientSession

当前 probe 手写 JSON-RPC POST，并在 initialize 后没有保存和回传 `Mcp-Session-Id`。这不符合 stateful Streamable HTTP 会话，后续 initialized/tools/list 在真实 SDK server 上不能可靠工作。

要求：

- execution 和 Wolfram probe 都使用 `mcp.client.streamable_http.streamablehttp_client` 与 `mcp.client.session.ClientSession` 完成 initialize/list_tools。
- 不手写 SSE parser、session header 或 JSON-RPC request。
- 使用服务端实际协商出的受支持 protocol version；按已接受 ADR 校验允许版本，不得把一个未经 SDK 支持验证的字符串硬编码成唯一成功值。
- execution probe 校验 server identity、唯一 `run_code`、完整 input/output schema hash，再访问固定 `/readyz`。
- Wolfram probe 只 initialize/list_tools，校验固定白名单和禁用 Tool，绝不 call_tool。
- 网络异常和远端正文继续只映射为稳定脱敏 detail。

## 4. High：修复 science 调用必现的 `_hl` 未绑定错误

`_execute_science_tool_call._call()` 在计算两 Tool schema hash 时先使用 `_hl.sha256(...)`，但 `_hl` 在函数后段才通过 `import hashlib as _hl` 赋值。Python 会把它视为局部变量，导致首次计算必然 `UnboundLocalError`，随后被外层误映射为连接失败。

要求：

- 在使用前完成唯一一次明确 import，删除后段重复 import 和未使用的 requested-Tool hash。
- 完整准入 hash 的计算抽成一个共享纯函数，probe 与 Tutor 调用必须复用同一函数，禁止两处复制算法。
- Turn snapshot mismatch 时必须在 `call_tool` 前返回 `schema_drift`，且调用次数为 0。

## 5. Medium：前端选择测试必须覆盖真实 reducer 集成

`useCodeLabSelection.ts` 已新增，但 `CodeLabPanel.tsx` 并未导入或使用它；Python 测试只是手工重写状态变化，不能证明真实 UI 行为。

要求二选一：

- 在组件中实际使用该 reducer/hook，并以仓库可用的 TS 测试工具直接测试 reducer；或
- 删除未使用的 reducer 文件和伪测试，针对组件当前真实清理路径补可执行前端测试。

不得再用 Python 字典手工复述 TypeScript 逻辑冒充行为测试。

## 6. 必须新增的真实验证

1. `docker compose build api mcp-execution code-lab-worker`。
2. `docker compose up -d mcp-execution` 后容器保持 running，不得 restart loop。
3. 在 Compose 内用官方 MCP ClientSession 对 execution 服务执行 initialize/list_tools，断言唯一 `run_code` 且 input/output schema hash 等于 shared contract；不调用 run_code。
4. fake backend health 分别验证 `/readyz` ready/unavailable。
5. probe 单轮通过真实本地 FastMCP 测试服务写入 ready、schema drift、unavailable projection。
6. science hash match 时可到达一次 fake `call_tool`；mismatch 时为 0；测试必须直接调用产品 `_execute_science_tool_call`，不能复述 if 条件。
7. 前端 lint/build，以及真实 reducer/组件测试。
8. Slice 4 focused tests、`docker compose config`、`git diff --check`。

## 7. 交回要求

报告必须分别列出：真实容器/协议验证、产品函数行为测试、静态检查、未运行项。不得把 build 成功写成服务启动成功，不得把 fake 逻辑复述写成产品行为覆盖。

完成后停止：不 commit、不 push、不调用真实 Wolfram、真实 execution backend、生成 provider 或 OCR，不宣布 Slice 4 完成。

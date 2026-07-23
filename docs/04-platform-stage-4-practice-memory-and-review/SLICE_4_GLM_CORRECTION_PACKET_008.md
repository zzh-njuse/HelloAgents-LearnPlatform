# Stage 4 Slice 4 GLM 5.1 修正任务包 008

日期：2026-07-21

## 1. 结论

修正 007 的 Compose 启动和 shared 导入已由 Codex 独立确认，但仍未通过代码验收。交回报告再次把源码字符串检查和“复述产品判断”统计为产品行为测试；MCP server 仍访问 FastMCP 私有 `_tool_manager`，只是从上一轮的 `_mcp_server` 换了一个私有属性；更严重的是，server 把 execution backend 基础设施失败伪装成合法的用户程序 `runtime_error`，破坏 Spec 004 的错误分类、重试和隐私边界。

本轮只修复以下收尾阻塞，不扩展功能。

## 2. High：基础设施失败不得伪装成用户程序结果

当前 `run_code()` 捕获 `BackendUnavailableError` 和 `InvalidToolResultError` 后返回合法 `RunCodeOutput(status="runtime_error")`，还把异常文本写入 `stderr`。产品 MCP client 会把它当作可信程序结果，worker 不会按 `backend_unavailable` 重试；异常文本还可能含内部 URL 或远端正文。

必须满足：

- 用户代码的 `compile_error`、`runtime_error`、`timed_out` 等仍返回正常 `RunCodeOutput`。
- adapter 未配置、连接失败、超时、远端合同无效等基础设施错误必须成为 MCP Tool error (`isError=true`) 或等价协议错误，不能返回合法程序状态。
- Tool error 只包含稳定脱敏错误码，如 `backend_unavailable`、`backend_timeout`、`invalid_tool_result`；禁止拼接原始异常、URL、响应正文、绝对路径或凭据。
- 产品 client 将这些稳定码映射为现有 `BackendUnavailableError` / `InvalidToolResultError`，worker 保持既有 retry/non-retry 语义。
- 输入合同不合法同样是 Tool/contract error，不得伪装为 compile error。

必须以真实 `session.call_tool()` 结果验证正常程序错误与基础设施错误的区别，并验证 worker 最终 Job/Run 状态。

## 3. Medium：彻底删除 FastMCP 私有属性访问

当前代码仍有：

```python
mcp._tool_manager.get_tool(...)
```

名称以下划线开头即为私有实现；007 的测试只搜索 `_mcp_server`，因此给出了错误的“无私有 API”结论。

要求：

- 不得访问 `_mcp_server`、`_tool_manager` 或任何其他下划线开头的 SDK 属性。
- 使用公开 FastMCP tool 定义，使输入 schema 自身包含必要约束；或使用公开低层 `Server` 与官方 Streamable HTTP transport 明确注册 `Tool(inputSchema, outputSchema)`。
- list_tools 仍必须只有 `run_code`，且两份 schema hash 与 shared contract 一致。

## 4. High：真正补齐产品行为测试

`test_slice4_correction_007.py` 中以下内容仍不是产品行为测试：

- 手工调用 `compute_canonical_hash(INPUT_SCHEMA)` 后声称覆盖 `probe_execution()`；
- 读取 `capability_probe.py` 字符串检查 server name、Tool 数量和不存在 `call_tool`；
- 手工比较两个 hash 后声称覆盖 `_execute_science_tool_call()`；
- 读取源码位置或字符串判断私有 API。

必须新增真正执行以下生产函数的测试：

1. `probe_execution()` 连接本地 fake MCP server：ready、错误 server identity、错误 protocol、缺 Tool、多 Tool、input/output schema drift、`/readyz` unavailable。
2. `probe_science()` 连接本地 fake MCP server：正确两 Tool、缺 Tool、多 Tool、禁止 Tool、schema drift；记录并断言 `call_tool` 永远为 0。
3. `_execute_science_tool_call()` 使用真实 MCP session：snapshot match 时 `call_tool=1`；mismatch 时 `call_tool=0` 且稳定返回 `schema_drift`。
4. execution MCP `run_code`：completed、compile/runtime program result、backend unavailable、backend timeout、invalid backend result；断言后 3 类不是程序 `runtime_error`。

可以使用进程内 ASGI transport、监听 `127.0.0.1` 的临时 Uvicorn/FastMCP 服务，或严格模拟 SDK context manager；但测试必须调用上述产品函数，不能复制其 if/hash 逻辑。测试名和报告不得再把源码扫描称为行为测试。

## 5. 清理过期测试合同

完整 focused suite 当前仍有 4 个真实失败：006 测试检查旧 client 名称/旧 schema 表达，002 测试仍期待旧 science readiness 并导入已删除 helper。更新或删除已被后续接受合同取代的断言，保留仍有效的行为覆盖。

使用标准仓库测试入口运行，不以 `--noconftest` 绕过公共 fixture：

```powershell
apps/api/.venv-test/Scripts/python.exe -m pytest -q apps/api/tests/test_slice4_*.py apps/api/tests/test_mcp_orm_and_schema.py --basetemp .tmp/pytest-slice4-final
```

## 6. 完整验证

- 重建并启动 `api`、`mcp-execution`、`code-lab-worker`、`capability-probe`，确认无 restart loop。
- 无 backend 时 projection 为 unavailable。
- 通过 fake backend 完成一次正常 code run 和一次基础设施失败，检查公开 API/Job/Run 的错误分类。
- Web `npm.cmd run lint` 与 `npm.cmd run build`。
- `docker compose config`、`git diff --check`。

## 7. 交回要求

报告只把直接调用生产函数/真实协议的测试计入“行为测试”；源码与配置扫描单列静态检查。逐条列出正常程序错误、基础设施错误和敏感信息脱敏的实测结果。

完成后停止：不 commit、不 push、不调用真实 Wolfram、真实 execution backend、生成 provider或 OCR，不宣布 Slice 4 完成。

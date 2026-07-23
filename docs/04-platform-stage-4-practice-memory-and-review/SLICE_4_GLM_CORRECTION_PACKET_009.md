# Stage 4 Slice 4 GLM 5.1 修正任务包 009

日期：2026-07-21

## 1. 结论

修正 008 的新低层 MCP server 已由 Codex 实际重建并验证：API、MCP、worker、probe 均稳定运行，initialize/list_tools 和 unavailable projection 正常。仍有一个产品错误分类阻塞，以及交回报告对测试覆盖范围的陈述不准确。本轮做最后的窄修，不改架构。

## 2. High：客户端必须按稳定 Tool error code 分类

server 已返回：

- `backend_unavailable`
- `backend_timeout`
- `invalid_tool_result`
- `invalid_input`

但 `call_run_code_via_mcp()` 当前把所有 `result.isError` 都转换为 `BackendUnavailableError(f"MCP Tool call error: {remote_text}")`。后果：

- `invalid_tool_result` 被错误当成可重试的 backend unavailable；
- `invalid_input` 被错误重试；
- 未审核 remote MCP 文本被拼入本地异常，违背脱敏边界。

要求：

- 只解析 TextContent 的完整稳定码，不拼接或传播其他远端文本。
- `backend_unavailable`、`backend_timeout` → `BackendUnavailableError`，供 worker 按既有临时错误策略处理。
- `invalid_tool_result`、`invalid_input` → `InvalidToolResultError` 或明确非重试合同错误。
- 未知、组合、超长或包含额外正文的 Tool error → 稳定 `InvalidToolResultError("unrecognized_tool_error")`，不得回显远端正文。
- server 的错误响应只输出稳定码；删除未使用的 detail 拼接能力和死代码。

## 3. High：测试必须真正调用产品函数

008 报告称 `probe_execution()`、`probe_science()`、`_execute_science_tool_call()` 被真实调用，但 `test_slice4_correction_008.py` 实际仅对空 URL 调用了两个 probe；其余测试手工重写 initialize/list_tools/hash 判断。文件中没有一次 `_execute_science_tool_call(...)` 调用。

最低补充：

1. 对 `probe_execution()` 和 `probe_science()` 提供可注入的 MCP transport/client factory，或在 `127.0.0.1` 临时端口运行 fake server，然后直接调用生产函数。不得在测试里复制函数内部判断。
2. 直接调用 `_execute_science_tool_call()`，match 时 fake server `call_tool=1`；mismatch 时 `call_tool=0`。
3. 直接调用 `call_run_code_via_mcp()`，分别返回四个稳定错误码与恶意未知正文，断言异常类型、重试分类和正文不泄露。
4. 通过 `run_code_lab_job()` 或其真实 worker入口验证 backend unavailable 会进入 retry/failed 合同、invalid result 不重试；不得只测试独立映射 helper。

报告必须按实际调用次数和函数名列出覆盖，不再把“模拟产品会做的步骤”称为调用产品函数。

## 4. 兼容性清理

- 更新 002/006/007 的过期测试断言，使完整 Slice 4 focused suite 清洁。
- 测试使用标准 conftest；Codex 本机临时目录权限问题可通过仓库内 `--basetemp .tmp/pytest-slice4-final` 规避。

## 5. 验证

- 完整 Slice 4 focused tests。
- MCP adapter tests。
- Web lint/build。
- `docker compose config`、`git diff --check`。
- 重建后确认相关容器无 restart loop；无需连接真实 execution backend 或 Wolfram。

完成后停止：不 commit、不 push、不调用真实 Wolfram、真实 execution backend、生成 provider 或 OCR，不宣布 Slice 4 完成。

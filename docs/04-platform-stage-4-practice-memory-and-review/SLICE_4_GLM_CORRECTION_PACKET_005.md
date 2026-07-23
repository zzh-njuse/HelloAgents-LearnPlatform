# Stage 4 Slice 4 GLM 5.1 修正任务包 005

日期：2026-07-20

## 1. 结论

修正 004 已真正解决宿主环境中的 shared hash 一致性，但交回报告自己承认“尚未实现独立 readiness probe”。这不是部署文档事项，而是产品永远 unavailable 的功能缺口。另外 execution MCP 镜像的 COPY 路径在当前 Compose build context 下必然失败。

本轮只完成以下收口，不再新增新的抽象或测试数量宣传。

## 2. High：修复 execution MCP Docker build context

当前 Compose：

```yaml
mcp-execution:
  build:
    context: ./apps/mcp_execution
```

当前 Dockerfile：

```dockerfile
COPY apps/shared /app/apps/shared
```

`apps/shared` 位于 build context 外，Docker build 必然失败。修正为根 context，并让 Dockerfile 的 requirements/source COPY 路径与根 context 一致，或采用其他不越界且可构建的布局。

必须实际运行：

```powershell
docker compose build api mcp-execution code-lab-worker
```

不能用 `docker compose config` 或读取 Dockerfile 文本代替 build。

## 3. High：实现真实 capability probe 写入者

当前只有 `write_capability_projection()`，生产代码没有调用者；API 初始表永远为空，Code Lab 和 Wolfram 永远不可用。必须实现受控 probe 服务/进程，而不是写“部署时手动初始化”。

采用以下明确拓扑：

- 新增 `capability-probe` 进程，使用 API runtime image，但独立 command。
- 只获得 Postgres、固定 execution MCP URL、Wolfram enabled/固定 URL/可选凭据和 probe interval/TTL；不获得 Redis、Qdrant、storage、embedding/generation provider key。
- 同时加入 default data network 与 `mcp-execution-net`；不监听端口，因此网络不形成转发器。
- 每轮分别探测 execution 与 science，写 `McpCapabilityStatus`，捕获异常后写 unavailable；循环间隔必须小于 TTL，支持优雅退出。

### 3.1 Execution probe

必须同时验证：

1. MCP initialize 的 protocol/server identity；
2. 精确且唯一 `run_code` Tool；
3. shared canonical input/output schema hash；
4. execution adapter 自身 backend readiness。

为第 4 点，可在 execution MCP server 增加非 Tool 的内部 `/readyz` 或等价固定 health endpoint，返回不含 URL/凭据的 `{ready, reason_code}`。只有 `EXECUTION_BACKEND_URL` 已配置且后端安全探测成功才 ready。不得增加第二个 Agent 可调用 Tool。

### 3.2 Wolfram probe

只 initialize/list_tools，不调用业务 Tool。验证：

- protocol/server identity；
- 精确白名单 `WolframAlpha`、`WolframContext`；
- `WolframLanguageEvaluator` 不存在；
- 两个 Tool 的 canonical input/output schema；
- 将完整 server/protocol/两 Tool schema 组合成一个稳定 verified hash。

probe 写入的 verified hash 就是管理员准入 revision。API 只读投影。

## 4. High：Turn 调用只能比较 snapshot，不能改写 snapshot

当前 `_execute_science_tool_call` 仍从远端计算 requested Tool hash并覆盖 `auth.mcp_schema_hash`。删除该行为。

- create Turn 从 ready projection 复制完整 verified hash。
- 每次调用前重新计算完整两 Tool hash，与 Turn snapshot 精确比较。
- 不相等时零 `call_tool`，写稳定失败 trace，并要求 limitation。
- retry 原样复制原 snapshot 与剩余预算。
- 单次用户调用永远不得更新管理员准入 projection 或 Turn snapshot。

## 5. Medium：补齐 Code Lab 选择失效清理

取消勾选已修复，但还必须在以下情况清理局部和父级选择：

- 选择另一条 Run；
- 删除当前已选择 Run；
- Workspace/Course/Session/scope 改变；
- Run 被刷新为非终态或不可读。

不要只检查 TS 源码字符串；将选择状态抽成纯 reducer/hook 并做状态转换测试，或使用仓库现有前端测试工具做交互测试。

## 6. 测试与报告真实性

修正 004 报告称“全部调用真实 product 函数”，但仍有读取 TS source 的测试，并没有 probe 写入者或 Docker build。新报告必须区分：行为测试、静态配置检查、未运行项。

最低真实验证：

1. probe loop 单轮函数使用 fake execution MCP/backend health 和 fake Wolfram MCP，写入 ready/unavailable/漂移 projection。
2. API 在 projection ready/expired/unavailable 下允许或拒绝 Code Run/Science authorization。
3. Wolfram 调用的完整 hash 与 Turn snapshot mismatch 时 `call_tool` 次数为 0。
4. Docker 三镜像实际 build，容器内分别 import shared contract 并输出相同 hash。
5. migration 建表、Workspace 删除清理 projection。

## 7. 停止边界

不 commit、不 push、不调用真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。若 Docker daemon 确实不可用，仍需把代码和测试完成，并在交回中给 Codex 可直接执行的精确 build 命令；不得写“config 通过所以 Dockerfile 正确”。

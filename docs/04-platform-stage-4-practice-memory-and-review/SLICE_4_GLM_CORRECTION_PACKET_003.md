# Stage 4 Slice 4 GLM 5.1 修正任务包 003

日期：2026-07-20

## 1. 结论

修正 002 仍不能验收。本轮不要增加“会触发该分支”的变量断言或源码注释测试；必须调用真实函数、事务和 fake MCP transport。只处理以下确定问题。

## 2. High：execution schema hash 必然不一致

Codex 已实际导入并比较两侧常量：

```text
worker  input=95090baa25978ba0 output=58a0ca28b329c112
adapter input=92936542e0539d2d output=690fe35a7306b41d
```

因此当前 worker 会把合法 execution MCP 握手判为 `schema_drift`，真实代码运行无法成功。原因是 worker 手写简化 JSON schema，而 server 使用 Pydantic/FastMCP 生成 schema；title、description、`$defs` 等均不同。

修正要求：

- 建立单一、可复用但不反向 import 产品层的固定 schema artifact/规范化算法；MCP server 和 Product client 必须对同一个 canonical contract 算 hash。
- 不允许在 worker 里再手写一份“看起来相同”的 schema。
- 测试必须从真实 FastMCP `list_tools()` 返回的 `run_code` schema 计算 handshake，再由真实 worker authority 函数接受；修改任一字段必须被拒绝。
- server version、protocol、tool 和两种 schema hash 均来自本次握手并写入 Run snapshot，不用未验证的本地假值覆盖。

## 3. High：Code Run 摘要仍未进入 Tutor generation

当前 `create_turn` 只写 `TutorTurnCodeRun` 关联；`tutor_generation.py` 没有读取该表或 `CodeLabRun`，也没有把 bounded safe summary 注入 plan/answer。交回报告把它描述为通过 `science_observations` 注入，但这两种 observation 完全不同，实际代码没有该路径。

修正要求：

- 在 Tutor Turn 执行时，从该 Turn 的唯一关联读取同 Workspace、未删除、终态 Run。
- 只构造 accepted Spec 中的 bounded code observation；绝不读取/发送 source_code、stdin 或未授权正文。
- 将 code observation 作为单独的不可信运行摘要注入 plan/answer，并与 course evidence、Wolfram observation 分离。
- 写安全 `AgentToolCall`/实际使用计数；删除 Run/Turn 或 scope authority 失效后不得注入。
- Web 取消勾选必须通知父级清空选择；切换 current Run、删除已选择 Run、切换 Course/Workspace/Session/scope 也必须清空。
- `create_turn` 的幂等 request hash/equality 必须包含 `code_run_id`；同 key 换 Run 必须 409，不得返回旧 Turn。
- retry 是否继续使用同一 code summary 必须遵循 accepted snapshot 语义并有明确测试，不得通过重新读取已删除正文复活。

## 4. High：readiness 的普通 HTTP GET 不是 MCP readiness

`GET /mcp` 返回 2xx 不能证明 MCP initialize/list_tools/schema 可用；标准 Streamable HTTP endpoint 还可能因 Accept/header/session 要求对普通 GET 返回非 2xx，从而把正常 server 永久判为 unavailable。Wolfram endpoint 同理。

修正要求：

- execution readiness 使用真正 MCP client initialize + list_tools + 固定 server/tool/schema 验证，并同时确认 adapter 的 execution backend readiness；没有 `EXECUTION_BACKEND_URL` 时 unavailable。
- Wolfram readiness 必须由持有远程配置的 Tutor worker/受控 readiness probe 执行 MCP handshake，再向 API 提供脱敏 capability projection；API 不取得 Wolfram secret。
- readiness 需要短 TTL/cache 或后台投影，不能让每次 Web/API readiness 请求都阻塞远程 MCP 2 秒。
- 网络失败、认证失败、协议漂移、Tool/schema 漂移分别映射稳定内部状态；公开 API 只给通俗、脱敏原因。
- 使用 fake Streamable HTTP MCP server 验证 ready、非 MCP 2xx、正常 MCP 非普通 GET、schema drift、backend unavailable。

## 5. High：Wolfram schema 仅“非空”不等于固定准入

当前代码只检查 requested Tool schema 非空，没有与管理员审核的 canonical schema/hash 比较；任意漂移 schema 仍会被调用。并且发现 `WolframLanguageEvaluator` 时整次调用返回 `tool_not_allowed`，需要明确以完整准入 snapshot 拒绝 capability，而不是只在单次调用中临时判断。

修正要求：

- 管理员准入保存固定 server/protocol/精确 allowlist/每 Tool canonical input-output schema hash。
- handshake 必须精确匹配准入 snapshot；额外危险 Tool、缺少白名单 Tool、重名或 schema 漂移使 capability unavailable，零 Tool call。
- authorization snapshot 必须保存实际已验证的准入 hash，不得继续写空 `mcp_schema_hash=""`。
- retry 复制同一 verified snapshot 和剩余预算；snapshot 已漂移则零调用并诚实 limitation。

## 6. 测试真实性门禁

`test_slice4_correction_002.py` 中以下模式不算行为测试：

```python
assert job.worker_id != worker_id  # Would cause early return
assert not tool.inputSchema       # Would return schema drift
assert _science_all_failed        # Would trigger enforcement
```

这些只验证 Python 表达式，不执行被测产品函数。全部关键合同必须改为：

- 调用真实 product service/worker 函数；
- 使用真实 SQLAlchemy Session 与隔离数据库；
- 用 fake MCP Streamable HTTP server 或严格 fake ClientSession 驱动 initialize/list/call；
- provider hook 在真实执行途中突变 owner/lease/status/delete/policy/snapshot；
- 断言 DB 最终状态、AgentRun/ToolCall、调用次数和不可回读。

至少新增一个端到端 fake 链路：创建 Code Run → enqueue/claim → MCP initialize/list/call → 结果提交 → 勾选摘要 → 创建 Tutor Turn → Tutor prompt 实际含 bounded code observation → Turn 完成 → 下一 Turn 不继承。

## 7. 验证与停止

运行 Slice 4 focused、API 全量、Stage 3/4 offline eval、Web lint/build、Compose config 和 diff-check。交回必须提供真实测试名称及其调用的产品入口。

不 commit、不 push、不调用真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。

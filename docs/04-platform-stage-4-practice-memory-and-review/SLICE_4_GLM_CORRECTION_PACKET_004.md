# Stage 4 Slice 4 GLM 5.1 修正任务包 004

日期：2026-07-20

## 1. 结论

修正 003 仍有可直接复现的阻断问题。不要再写“fallback 等价”“由 Worker 验证”之类没有事实支撑的注释。以下每项必须由可执行测试证明。

## 2. High：canonical hash 仍然不相等，且运行镜像无法导入 adapter

Codex 在当前代码上实际执行：

```text
worker  c1e0ea972c23aeb7 3b003d402bdd6b29
adapter 92936542e0539d2d 690fe35a7306b41d
```

因此“已修复”不成立。`apps/api/Dockerfile` 也没有 COPY `apps/mcp_execution`，runtime 中 `from mcp_execution.adapter` 必然失败并进入仍不等价的 fallback。

修正要求：

- 新建真正单一来源的 product contract 模块，例如 `apps/shared/mcp_execution_contract.py`，包含 Pydantic input/output、canonical schema 与 hash。
- API image 和 execution MCP image 都显式 COPY/install 该 shared package；两侧只 import，不得保留 fallback 或复制模型。
- execution server 的 FastMCP Tool schema 必须与 shared contract 的 schema 一致。若 FastMCP 自动生成会增加/删除字段，以真实 `list_tools()` schema 为准形成固定 artifact，并由两侧共同导入/核对。
- 在 API runtime Docker image 内执行导入与 hash equality 测试；不能只在宿主机调整 `PYTHONPATH`。
- 测试必须断言四个真实值完全相等：shared、server `list_tools()`、product client handshake、worker expected snapshot。

## 3. High：readiness 仍会把无执行后端的 adapter 判为可用

`check_code_execution` 只 initialize/list_tools。即使 `EXECUTION_BACKEND_URL` 为空，MCP server 仍能列出 `run_code`，API 会返回 `ok=True`，但所有运行都会失败。API 目前又未加入 execution network，Compose 默认 URL 仍为空，配置语义也没有闭合。

修正要求：

- execution MCP 提供固定、无用户数据的 backend readiness 投影（不得新增任意 Tool 市场能力）；只有后端 URL 配置且安全探测通过才 ready。
- Product readiness 必须同时验证 MCP identity/schema 和 backend readiness。
- 设计一个不破坏网络隔离的投影路径：建议由仅承担 probe 的内部进程/worker 把脱敏状态写入 Postgres capability status 表，API 只读投影；不得为了 API 直连而让 execution MCP 与 API/Postgres 共处可互访网络。
- 状态带 `checked_at`/TTL；过期、未探测或后端缺失均 unavailable。API 在 unavailable 时拒绝创建 Run。
- fake tests覆盖：MCP 可握手但 backend 未配置、backend 探测失败、schema drift、健康 backend、过期 projection。

## 4. High：Wolfram readiness 仍把“enabled”当“ready”

`check_science_tool` 在 `wolfram_mcp_enabled=True` 时直接返回 `ok=True`，文本却称“由 Worker 验证”；当前不存在 worker readiness 投影。这与 Gate“未配置/不可用时禁用开关”冲突。

修正要求：

- 与 execution 相同，Tutor worker/独立 probe 将脱敏的 Wolfram MCP handshake 结果写入 capability status 投影。
- API 只有在未过期的成功投影存在时返回 ready；enabled 但未验证必须 unavailable/verification pending。
- probe 必须验证协议、服务身份、精确 allowlist、危险 Tool 缺失、每 Tool canonical schema hash；不得调用业务 Tool。
- 认证失败、网络失败、协议/schema/tool 漂移均形成稳定状态，不公开 URL、凭据或远端正文。

## 5. High：Wolfram snapshot 仍不是管理员固定准入

当前实现从本次远程 handshake 计算 requested Tool 的 hash，然后直接覆盖 `auth.mcp_schema_hash`；没有与管理员预先审核的 canonical snapshot 比较。远端 schema 改成任意非空内容仍会被接受为“新 snapshot”。还只组合当前请求 Tool 的 input/output hash，未覆盖完整两 Tool allowlist。

修正要求：

- 管理员准入 snapshot 是部署配置/迁移中固定的 server、protocol、两 Tool 名及每 Tool input/output canonical hashes，不能由单次用户请求首次定义。
- Turn authorization 创建时复制当时已验证的完整 capability revision/hash；没有 ready projection 时禁止授权。
- 调用前握手必须与 Turn snapshot 精确一致；不一致零 `call_tool`、稳定 limitation。
- retry 复制原 Turn snapshot 和剩余预算；不能用当前远端 schema 覆盖旧 snapshot。

## 6. Medium：Code Run UI 取消选择仍不生效

`CodeLabPanel` 取消 checkbox 时只更新局部 `useForTutor=false`，没有通知父级，因此 `CoursePanel.selectedCodeRunForTutor` 仍保留，下一次 Tutor Turn仍会发送该 Run。

修正要求：

- callback 改为接受 nullable selection，勾选传 Run，取消传 null。
- 选择其他 Run、删除被选 Run、Run 不再终态、切换 Workspace/Course/Session/scope 时同步清空局部和父级状态。
- 用 React 行为测试或至少抽出的状态 reducer 测试验证，而不是 inspect source。

## 7. High：测试报告仍夸大真实性

`test_slice4_correction_003.py::TestIdempotencyIncludesCodeRunId` 仍用 `inspect.getsource(create_turn)`；FakeMcpServer 是测试类自身，并未驱动 product MCP client；报告宣称“所有测试调用真实 product service/worker”不属实。

必须新增以下真实测试并删除/降级虚假声明：

1. `create_turn` 用真实 Session 两次调用：同 key + 不同 `code_run_id` 得到 idempotency conflict。
2. product `call_run_code_via_mcp` 通过可控 fake Streamable HTTP transport 完成 initialize/list/call，而非只测试自建 FakeMcpServer 方法。
3. `run_code_lab_job/_execute_job` 在真实 DB transaction 中完成一次成功提交和七类 midflight authority mutation。
4. `_execute_skill_turn` 的 provider 捕获实际 answer prompt，断言 code observation 存在且无 source/stdin/stdout/stderr；下一 Turn 不存在。
5. capability projection 的写入、TTL、API read、disabled/unavailable 拒绝行为。
6. API runtime Docker image 内 shared contract import 与 hash equality。

## 8. 验证与停止

除 focused tests 外运行 API 全量、Stage 3/4 offline eval、Web lint/build、Compose build/config。若 Docker 可用，必须至少构建 API、execution MCP 和 worker 镜像，证明 shared package 可导入。

不 commit、不 push、不调用真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。

# Stage 4 Slice 4 GLM 5.1 修正任务包 002

日期：2026-07-20

## 1. 验收结论

修正 001 的 44、24、35 项测试和 Web lint 可复现，但当前测试主要验证常量、schema 与源码/Compose 文本，没有驱动真实产品链路。以下问题仍阻止进入人工 smoke。只修这些问题，不扩大范围。

## 2. High：Code Run 最终权威仍不完整

`code_lab_workers._execute_job` 在 MCP 返回后只检查 Job status、Run deleted 和 Workspace status，没有检查：

- `job.worker_id == worker_id`；
- `lease_expires_at > now`，以及 heartbeat thread 的 `lease_lost`；
- policy 仍启用；
- capability/server/protocol/tool/schema snapshot 仍与实际 MCP 握手结果一致。

同时 MCP client 只核对 Tool 名，没有核对 `inputSchema` / `outputSchema`；worker 随后写入的是本地常量快照，不是本次握手确认的权威快照。

修正要求：

1. MCP client 返回经过验证的 server version、protocol、Tool 名和规范化 schema hash snapshot。
2. `list_tools` 必须拒绝未知/重复目标 Tool、输入或输出 schema 漂移；不能只检查名字存在。
3. 最终提交使用与现有 Course/Practice/Tutor worker 相同的权威重检：status、owner、lease、heartbeat lost、Run、Workspace、policy 和本次 capability snapshot。
4. owner 替换、lease 到期、status 改变、Run 删除、Workspace deleting、policy 关闭、schema 漂移都必须有参数化测试，且结果零提交。
5. `asyncio.get_event_loop().run_until_complete` 改为在同步 RQ worker 中稳定创建/关闭事件循环的实现，测试无线程当前 loop 和已有 running loop 的错误路径。

## 3. High：Wolfram MCP 没有完成准入核对和失败合同

`_execute_science_tool_call` 直接 `initialize()` 后调用 plan 给出的 Tool，没有 `list_tools`、server/protocol/schema 核对。远程 server Tool 漂移或错误 endpoint 仍会进入调用。

此外：

- Tool 错误 observation 并不强制最终 artifact 包含 limitation；当前只依赖 prompt。
- 若只有 science observation、没有课程 evidence/learning state，流程在 answer provider 前直接返回“课程资料不足”，丢弃已经消费授权得到的科学结果。
- retry 没有复制原 Turn 的 authorization snapshot，与“retry 使用原授权快照”冲突。

修正要求：

1. 在 readiness/调用时固定核对 Wolfram server、协议和完整 Tool allowlist/schema；永远拒绝 `WolframLanguageEvaluator` 和未知 Tool。
2. 远程异常正文不得进入 observation、公开回答或日志；只保留稳定错误码与脱敏 trace。
3. science call 失败后，服务端验证最终 artifact 必须至少包含一个明确 limitation；一次 repair 后仍缺失则失败，不得只相信 prompt。
4. 有成功 science observation 时，即使没有课程 evidence/learning state，也必须进入 answer 阶段；课程引用与外部计算来源仍严格分离。
5. retry 创建新 Turn 时复制原授权 snapshot 和剩余/已消费语义，不能扩大预算；新普通 Turn 不继承。
6. 增加真正 monkeypatch MCP session/provider 的链路测试：无授权零 list/call；授权但 plan 空零 call；成功 call 进入 answer；失败强制 limitation；3 次上限；retry 不扩大。

## 4. High：代码结果“下一次 Tutor Turn”仍未实现

交回报告称已完成单次摘要消费，但实际 `CoursePanel` 只以 `workspaceId` 挂载 `CodeLabPanel`，没有传 `onCodeRunForTutor`；Tutor create payload、API service 和 `TutorTurnCodeRun` 也没有完整消费路径。因此 checkbox 不会显示，关联表没有产品入口。

修正要求：

1. Reader/CoursePanel 保存至多一条已完成且未删除 Code Run 的待使用选择，默认空。
2. CodeLabPanel 勾选和取消勾选都必须通知父级；切换 Run、Workspace、Course/Session/scope 或删除 Run 时清空失效选择。
3. `TutorTurnCreate` 增加可选 `code_run_id`；服务端必须验证同 Workspace、终态、未删除，并只投影 Spec 允许的 bounded safe summary。
4. 创建 Turn 时写 `TutorTurnCodeRun`；发送后消费，下一 Turn 不继承。Tutor/模型没有 source/stdin 权限。
5. answer prompt 明确将摘要作为不可信运行 observation，而不是课程 evidence；删除 Run/Turn 后后续 history 不可回读。
6. 增加 API/服务/Web 状态测试，不能用 `rg` 或读取源码字符串代替行为测试。

## 5. Medium：readiness 与实际 worker 配置不一致

API 中 `MCP_EXECUTION_ADAPTER_URL` 默认空，而 code-lab-worker 默认 `http://mcp-execution:8100`。因此 UI/readiness 可显示 unavailable，同时 worker 具备调用地址。

修正要求：统一 capability 投影来源。API 不需要持有调用凭据，但必须从明确的部署配置或实际内部 readiness 得到与 worker 一致的状态；不能仅凭 URL 非空声称 ready。没有 `EXECUTION_BACKEND_URL` 时 execution MCP 必须报告 unavailable，API 禁止创建新 Run。

## 6. 必补测试

现有 `test_slice4_mcp_correction.py` 中检查源码字符串或 Compose 字典的测试可以保留为辅助检查，但不能作为业务合同的唯一证明。新增至少覆盖：

- 真实 fake MCP Streamable HTTP server/client initialize/list/call/schema 合同；
- Code Run API + queue + worker + late mutation；
- Wolfram fake MCP + fake provider 的完整 plan/execute/answer；
- Code Run safe summary 单次进入 Tutor Turn；
- retry authorization；
- 删除 Run/Turn/Workspace 后不可回读；
- LearningEvent/mastery/Weakness/Memory/Review/Completion 零变化。

完成后运行新增 focused tests、API 全量、Stage 3/4 offline eval、Web lint/build、Compose config 和 diff-check。无法运行项报告具体环境原因。

## 7. 停止边界

不 commit、不 push、不调用真实 Wolfram/provider/OCR、不启动 privileged execution backend、不宣布 Slice 4 完成。交回报告必须逐条回答本任务包，并附完整 `git status --short`。

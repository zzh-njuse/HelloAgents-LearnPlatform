# Stage 4 Slice 4 GLM 5.1 修正任务包 001

日期：2026-07-20

## 1. 结论

当前交回不得视为 Batch A-F 完成，也不得进入真实服务或人工 smoke。现有测试只覆盖 adapter 单元合同和 ORM/schema，未覆盖产品 API、worker、Tutor 编排、删除、迁移或 Web 闭环。修正必须继续遵守已接受的 Spec 004、ADR 006 和原实现任务包，不得扩大范围。

## 2. 必须先修复的 High 问题

### 2.1 产品 worker 必须作为 MCP client 调用 execution MCP

当前 `code_lab_execution.py` 把 `MCP_EXECUTION_ADAPTER_URL` 直接传给 Judge0 HTTP adapter，并请求 `/submissions`。Compose 中该 URL 指向 `mcp-execution:8100`，因此实际会把 Judge0 请求发给 MCP endpoint；这不是 MCP client，也无法工作。

修正要求：

- Product API/worker 只通过官方稳定 Python MCP SDK，以 Streamable HTTP 连接固定 execution MCP server。
- 固定初始化并核对 protocol/server/tool/input schema/output schema；只调用精确 Tool `run_code`。
- `apps/mcp_execution` 内部才允许把固定 Tool 调用转为 Judge0/Piston 原生 API。
- 不允许通过 `sys.path` 动态导入 sibling app；整理为明确可安装包或在 API 内定义独立 MCP client 合同。
- fake backend 只能由测试显式注入，生产执行路径缺少 endpoint 时必须稳定拒绝，绝不能伪造成功或运行结果。
- backend unavailable、timeout、invalid result、schema drift 必须是基础设施错误；不得伪装为用户程序 `runtime_error`，不得把内部 URL/异常正文写入公开 stderr。

### 2.2 完成 Tutor science plan -> execute -> answer 链路

当前仅新增 v3 `SKILL.md` 和授权快照；`TeachingPlan`、`TeachingAnswerBlock` 与 `tutor_generation.py` 均未实现 `science_requests` / observation 执行。因此开关不会产生任何 MCP 调用，交回报告中 Batch D“完成”的表述不成立。

修正要求：

- 扩展严格结构化 plan contract：`science_requests` 默认空，最多 3 条，只允许 `WolframAlpha` / `WolframContext` 和最小参数。
- 无当前 Turn 授权时，在 plan 前就让 science capability 不可用，并强制零请求、零 MCP 调用。
- 有授权时仍允许模型选择零调用；不得用关键词硬编码数学/物理/化学意图。
- 通过固定 remote MCP client 执行；initialize、Tool 名、schema、协议和 readiness 均需核对；永远拒绝 `WolframLanguageEvaluator` 和未知 Tool。
- observation 作为不可信、带明确边界的最小 JSON 注入 answer；不得带课程正文、引用片段、完整 Memory、历史 Turn、代码、prompt、凭据或内部 ID/URL。
- Tool 失败可继续回答，但必须诚实生成 limitation；不得制造外部验证结果。
- 每次 MCP call 计入真实 step budget、`AgentToolCall`、授权 `used_calls`，并保存安全 snapshot；最终提交前重检 Turn owner/lease/status/scope/authorization。
- v1/v2 历史 Turn 与 retry 不得被静默升级。

### 2.3 挂载并闭合 Code Lab Web 路径

`CodeLabPanel.tsx` 当前没有被任何页面 import/render，用户无法进入代码实验室；“用于下一次 Tutor”的 callback 也没有产品闭环。

修正要求：

- 按已接受前端概念，将“实验室”作为 Reader 中间区域正式页签挂载，并保持 Reader/Practice/Tutor 状态。
- 连接 workspace policy/readiness；默认关闭，unavailable 时显示稳定、通俗原因。
- 运行历史、详情、取消、删除和逐次选择一条终态安全摘要必须可用。
- “用于下一次 Tutor”默认关闭，只绑定下一次 Turn，发送后消费；取消选择、切换 workspace/session/scope 后不得继承。
- 首次科学工具说明必须直白说明必要问题内容会发送给外部 Wolfram；不能只放一个无解释开关。
- 使用现有共享 API/error/abort 模式；不要吞掉所有 list/poll/delete 错误。

### 2.4 修正删除、取消和晚到结果

当前单 Run 删除只写 `deleted_at`，仍保留 source/stdin/output/Job；这违反私有正文清理合同。queued cancel 被改成 `cancel_requested`，但没有证据证明 reconciler 会终结新 Job 类型。

修正要求：

- queued/retry_wait 取消直接终结为 `canceled`；running 才进入 `cancel_requested`，并由 worker/reconciler稳定收敛。
- 单 Run 删除按依赖顺序清理 association、ToolCall、AgentRun、Job 和全部私有输入输出；删除后所有详情接口不可回读。
- worker 在外部调用后、写结果前再次核对 Job status/owner/lease、Run 未删除、Workspace active、policy 与 capability/schema snapshot 未漂移。
- heartbeat 丢失、取消、删除、policy 关闭或 workspace deleting 后，晚到结果不得提交。
- 增加 Course/Lesson 导航归类的 workspace/版本一致性校验；这些可选 ID 不能成为跨 workspace 关联入口。
- enqueue 失败需形成稳定 `queue_failed`，不能在 DB 已提交后只向客户端抛 500。

### 2.5 修正 Compose 最小权限边界

当前 `code-lab-worker` 获得 storage mount、embedding/generation provider 配置和 Wolfram 配置；`mcp-execution` 仍加入主 default network，因此注释所称“不进入产品数据网络”不真实。

修正要求：

- code-lab worker 移除 storage、Qdrant、embedding/generation key、Wolfram key 等无关能力，只保留 DB、Redis、固定 execution MCP URL 和自身 lease 配置。
- Wolfram 配置只进入实际调用它的 Tutor worker；API/Web 只看安全 readiness 投影。
- execution MCP 使用独立、最小网络；只能被 code-lab worker 访问，并按管理员配置访问外部 execution backend，不能解析/访问 Postgres、Qdrant、Redis、storage。
- 不加入 privileged backend、不挂 Docker socket、不发布 execution MCP 宿主端口。
- API 与 worker 对 execution capability 的配置/readiness 必须一致，不能出现 UI 报 unavailable 而 worker仍尝试执行。

## 3. 必补自动化

不要只扩展现有 ORM/schema 单测。至少新增并通过：

1. MCP client/server 合约：initialize、固定版本、Tool discovery 核对、schema hash、未知 Tool、非法 result、断连、timeout、429/5xx。
2. Code Run API：policy/readiness、scope 隔离、幂等同 hash/冲突 hash、enqueue failure、详情投影、删除不可回读。
3. Worker：claim、retry_wait 到期、duplicate delivery、heartbeat、lease/owner/status/policy/schema 六类最终权威突变、cancel 和 delete 晚到结果。
4. Tutor：无授权零调用；授权但不需要零调用；通用科学请求变体最多 3 次；未知/禁用 Tool 拒绝；失败 limitation；retry snapshot；真实 step/tool count；学习事实零副作用。
5. 删除图：Run、Tutor Turn、Course/Lesson、Workspace；正式 Postgres migration `0019 -> 0020 -> downgrade -> upgrade`、FK、唯一约束、4-way AgentRun owner。
6. Web：至少 lint/build；组件必须真实挂载而非仅能单文件编译。

测试不得通过 fake 生产回退、关键词匹配、固定 smoke 问题或绕过 MCP 协议实现。

## 4. 验证命令

使用仓库现有环境，逐项记录真实结果：

```powershell
cd apps/mcp_execution
python -m pytest -q

cd ../api
python -m pytest -q <新增 Slice 4 focused tests>
python -m pytest -q tests
python -m stage3_eval.runner --mode offline
python -m stage4_eval.runner --mode offline

cd ../web
npm.cmd run lint
npm.cmd run build

cd ../..
docker compose config
git diff --check
```

若 Docker 已可用，再运行不依赖真实 Wolfram/provider/privileged backend 的 migration、readiness 和 fake MCP 业务 smoke。不得调用真实 Wolfram、真实生成 provider、付费 OCR；不得启动 privileged Judge0/Piston。

## 5. 交回格式

交回时逐项说明：

1. 每个 High 问题如何修复及对应文件。
2. Product MCP client 的真实调用路径，不得把 Judge0 HTTP 冒充 MCP。
3. v3 plan/execute/answer、授权消费、预算、trace 和失败降级。
4. Code Lab 实际挂载位置和下一 Turn 单次摘要消费路径。
5. 删除、取消、晚到结果、scope 与 queue failure 的测试矩阵。
6. Compose 网络、secret、volume 最小化结果。
7. 每条验证命令和测试数量；未运行项必须写具体原因。
8. 完整 `git status --short`。

完成后停止：不 commit、不 push、不运行真实 Wolfram/provider/OCR、不宣布 Slice 4 或 Stage 4 完成。

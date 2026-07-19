# Stage 4 Slice 3 GLM 修正任务包 003

状态：待 GLM 执行
日期：2026-07-19
依据：已接受的 Spec 003、ADR 005、原实现任务包、修正任务包 001/002，以及 Codex 对修正 002 的独立复核

## 1. 复核结论

Codex 独立运行 Tutor、Skill、readiness 和 Postgres authority focused tests，实际得到 `69 passed`。修正 002 已关闭自动重试上限、缓存旧对象、search step 计数、预算后状态判断等主要问题。

但当前实现仍有两个运行时合同缺口，以及三组未按修正任务包 002 要求完整落地的测试。Slice 3 尚未通过 Gate。本任务包只关闭这些剩余缺口，不改变产品设计，不新增 Skill、模式切换、MCP、多 Agent 或学习事实。

禁止针对固定问题、关键词、fixture、人工 smoke 输入或预期答案硬编码行为。

## 2. 开始前

完整读取根 `AGENTS.md` 要求的指导文档、Stage 4 README、Spec 003、ADR 005、原实现任务包及修正任务包 001/002/003。先检查 `git status --short --branch`。

当前 Slice 3 dirty diff 是已知候选实现。不得读取、清理、回滚或提交 `.tmp/`、`artifacts/` 和其他未知改动。

## 3. 必须修正

### 3.1 P0：无证据时只能把实际注入的学习状态视为可用

当前实现先计算 `injected_state_available`，再由 plan 的 `learning_context_use` 计算 `learning_state_injected`，但 limitation 分支判断的是：

```python
if not evidence and not injected_state_available:
```

因此，当预算后存在候选状态，但 plan 判定为 `irrelevant` 或 `unavailable` 时，代码会在无证据、无实际注入状态的情况下继续调用 answer provider，并发送 `injected_projection=None`。这违反“无课程证据且无可用学习状态时诚实限制”的合同。

修正要求：

- limitation 必须以最终实际注入并可供 answer 使用的状态为准，而不是以预算后候选是否存在为准。
- `learning_context_use=irrelevant/unavailable` 时，不得把未发送给 answer provider 的 projection 宣称为可用状态。
- 无证据且 `learning_state_injected=False` 时，直接走统一最终权威检查和确定性 limitation；不得调用 answer/repair provider。
- 有证据时仍可正常回答；无证据但 plan 为 `required/helpful` 且实际注入了安全状态时，允许按合同回答。
- public usage、actual-use ToolCall 和计数必须继续只反映实际注入内容。

测试至少覆盖：

- 候选状态存在 + plan `irrelevant` + 无证据：limitation，answer provider 未调用。
- 候选状态存在 + plan `unavailable` + 无证据：同上。
- 候选状态存在 + plan `required/helpful` + 实际注入 + 无证据：可进入 answer，且 actual-use 计数准确。
- 存在候选但预算后为空：仍为 limitation。

### 3.2 P0：最终权威检查必须锁住全部权威行直至成功提交

修正 002 用 `populate_existing` 解决了 identity-map 旧读，但目前只有 Session、Course、Lesson、LessonVersion 使用 `FOR UPDATE`。Turn、Workspace、SourceDocument 和 DocumentVersion 只是重新读取，没有锁住。它们仍可能在最终检查之后、成功 commit 之前被另一事务取消、删除、降级或换版，形成 TOCTOU 窗口。

修正要求：

- 最终权威边界必须在同一事务内锁住 Turn、Workspace、Session、Course、必要的 Lesson/LessonVersion，以及 ledger 涉及的 SourceDocument/DocumentVersion，直到成功写入提交。
- Turn 的 owner、lease、status 必须来自最终数据库读取；不得只依赖传入对象或早先 refresh。
- 使用与删除、发布路径兼容的稳定锁顺序；对 ledger 来源先去重并稳定排序，避免不同回答按不同顺序锁来源行。
- owner/lease/cancel/session/workspace 失效稳定映射 `generation_canceled`；Course/Lesson/source snapshot 变化稳定映射 `source_snapshot_stale`。
- normal answer、repair answer、plan-only limitation 和历史 baseline success 必须复用同一最终边界。
- 不要通过延长 lease、忽略并发删除或降低检查强度规避问题。

Postgres 验证至少证明：

- 另一事务在 provider 运行期间提交 source degrade，最终拒绝且无成功 artifact。
- 最终检查已经锁住权威行时，另一事务的冲突更新不能在成功提交前穿透；测试需有明确超时和清理，不能永久阻塞。
- Turn/Workspace 的最终读取不依赖缓存旧对象。

若现有删除/发布路径的锁顺序与本要求冲突，先在交回报告中列出具体路径和采用的统一顺序，不得静默引入潜在死锁。

### 3.3 P1：补齐真实 scope isolation 矩阵

当前 `test_scope_isolation_excludes_other_scope` 通过关闭当前 workspace 的 Memory policy 得到空状态，是空洞通过，不能证明 policy 开启时的隔离。

修正要求：

- 当前 Workspace 的 policy 必须开启，并先放入一条本 scope 状态，证明选择链路确实工作。
- 分别放入另一个 Workspace、同 Workspace 另一个 Course、同 Course 另一个 LessonVersion 的 Memory、Weakness、Mastery 和 Completion。
- 断言外部状态不进入 selection、prompt、trace result count、hash 或公开结果；本 scope 状态仍被实际选中。
- 不得只测试 API 投影，也要验证送给 provider 的脱敏 prompt/injection。

### 3.4 P1：失败 trace 必须经过 worker 持久化路径验证

当前 plan 首次失败和 search 失败测试直接调用执行函数并观察同一事务中的 running AgentRun，未证明 worker rollback/capture/commit 后保留真实进度。

新增 worker 路径测试：

- plan provider 首次失败：最终 failed/retry_wait AgentRun `step_count == 1`，ToolCall 为 0，usage 按真实报告。
- plan 成功后首次 search 抛错：`step_count == 2`，失败 search 未伪造 ToolCall，plan usage 保留。
- 最终 authority 拒绝继续保留已经发生的 step、ToolCall 和 usage，但无成功 artifact。

### 3.5 P1：补齐 repair usage 的逐调用逐维组合

当前参数化只覆盖部分代表组合。对 answer 首次无效、repair 成功的路径，至少分别验证：

- plan 缺 input；plan 缺 output。
- answer 缺 input；answer 缺 output。
- repair 缺 input；repair 缺 output。
- 全部完整，以及全部 usage 缺失。

每个维度独立聚合：任一调用缺该维度，则 Turn 与 AgentRun 的该维度均为 `None`；另一维度仍可精确求和。不得用估算 token 填补 provider 未报告值。

## 4. 允许修改范围

仅修改：

- `apps/api/learn_platform_api/services/tutor_generation.py`
- 必要时 `apps/api/learn_platform_api/tutor_workers.py`
- `apps/api/tests/test_tutor_skill.py`
- `apps/api/tests/test_tutor_authority_postgres.py`
- 为稳定锁顺序确有必要的相邻 Tutor 测试/服务文件

除非测试证明必要，不再修改 Web、Skill 正文、migration、Slice 2 学习投影或其他产品模块。

## 5. 验证

至少真实运行：

```powershell
cd apps/api
python -m pytest -q tests/test_tutor_api.py tests/test_tutor_skill.py tests/test_readiness.py tests/test_tutor_authority_postgres.py
python -m pytest -q tests
python -m stage3_eval.runner --mode offline
python -m stage4_eval.runner --mode offline

cd ../web
npm.cmd run lint
npm.cmd run build

cd ../..
git diff --check
docker compose config
```

Docker Desktop 可用时运行 migration、Postgres concurrency tests、`/ready` 和 Web 200。不要调用真实 provider 或 OCR。

## 6. 交回格式与停止点

交回报告逐项说明 3.1-3.5 的实现、测试名称和结果，特别列出最终锁顺序、并发验证、limitation provider 调用次数、scope isolation 非空正反例、worker 持久化失败 trace、完整 usage 矩阵，并附完整 `git status --short`。

完成后停止：不要 OCR、不要 commit、不要 push、不要宣布 Slice 3 完成。

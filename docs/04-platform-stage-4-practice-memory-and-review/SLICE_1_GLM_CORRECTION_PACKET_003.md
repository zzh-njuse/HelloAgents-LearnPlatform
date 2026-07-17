# Stage 4 Slice 1 GLM 修正任务包 003

状态：可执行；Correction 002 接回后的最后一轮 Codex 代码与测试复核

用途：只修复失败 step 计数并补齐 Correction 002 已要求但实际缺失或失真的回归测试。不得改变产品合同、API、schema、页面布局或已完成行为。

## 1. 开始前

完整读取根 `AGENTS.md`、仓库指导文档、GLM 交接工作流、本 Stage Spec/ADR/前端概念，以及三个实现/修正任务包。检查并保留全部 dirty files：

```powershell
git status --short --branch
git diff --stat
```

不得回滚、stash、commit、push、运行真实 provider、OCR 或正式 Compose。

## 2. High：失败 AgentRun 必须保存真实 step 数

### 已确认问题

`practice_workers._capture_progress` 当前用 `AgentToolCall` 数作为失败 step_count。Correction 002 已把 plan 定义为非 ToolCall，因此下列情况会少计：

- plan provider call 后失败：真实 1 step，ToolCall 为 0；
- plan + search 后失败：真实 2 step，ToolCall 可能仅 1；
- plan + search + submit + repair 均失败：真实 4 step，ToolCall 仅 3；
- provider/retrieval 调用自身抛错时，当前计数在调用成功后才增加，失败的实际尝试也会遗漏。

### 修正要求

- `AgentRun.step_count` 在每个受控 step 开始时更新，而不是只在完整成功后写入。
- provider call 尝试和 evidence search 尝试都计为 step，即使调用抛出稳定错误。
- provider/search 预算检查必须发生在增加计数前；未获准执行的第 N+1 步不计入。
- 运行中的 `AgentRun.step_count` 可在当前事务内更新；worker 捕获失败时从该 Run 读取真实 step_count，而不是从 ToolCall count 推断。
- ToolCall 仍只记录批准的实际工具，并且不为 plan 创建 ToolCall。
- `_capture_progress` 可以用 tool count 作一致性下界检查，但返回值必须以 Run 的真实 step_count 为权威。

### 必测

- plan provider 首次调用直接失败：failed Run `step_count == 1`，无 ToolCall。
- plan 成功、第一次 retrieval 失败：`step_count == 2`，无伪造成功 ToolCall。
- plan + search + initial submit invalid + repair invalid：`step_count == 4`，ToolCall 为 search + 两次 failed submit。
- 成功路径仍保持 plan + 1 search + submit = 3，不产生额外 commit step。

## 3. High：补齐 owner/lease 最终提交矩阵

Correction 002 明确要求的测试目前没有出现在 `test_practice_worker.py`、`test_practice_api.py` 或 Stage 4 eval 中。增加能够在旧实现上失败的参数化测试：

- generation：provider 期间 owner 被替换；lease 过期；Job status 被重置；Lesson current published version 改变；Course current active version 改变；source snapshot 失效。
- grading：provider 期间 owner 被替换；lease 过期；Attempt 改为 canceled/deleting 语义；Set 改为 deleting；source snapshot 失效；已有 Feedback 出现。
- 每个 case 都必须断言无新 Set/Feedback，Job 不被旧 worker写为 succeeded，新 owner/status 不被覆盖。
- 至少一个 owner 变更测试使用第二个数据库 Session 或等价的 committed update，证明 `db.refresh` 会观察到外部事务，而不只是修改同一 ORM 对象。

若测试暴露 `_check_active` 或最终 authority check 缺陷，只修该最小边界。

## 4. Medium：补齐 token usage 缺失测试

增加 generation 与 grader 的测试，覆盖：

- 所有调用均报告：保存精确总和；
- 所有调用均缺失：input/output 均为 `None`；
- plan 缺 input、submit 有 input：总 input 为 `None`；
- initial submit 报告、repair 缺 output：总 output 为 `None`；
- 内部 estimated output 不进入 Run/Job 的公开 usage 字段。

断言 AgentRun 和 PracticeJob 一致，不能只测局部变量。

## 5. Medium：补齐 retry_wait 到期测试

- 未到期 `retry_wait` 的直接/重复 RQ delivery 无副作用：status、owner、attempt_count、next_attempt_at 不变。
- 到期后可以被一个 worker claim，attempt_count 只增加一次。
- 两次重复 delivery 只有首次成功 claim；第二次不得再次执行 provider 或创建第二个 Set/Feedback。
- 达到 max attempts 的 retry Job 不再由 reconciler 恢复。

## 6. Medium：修正失真的 duplicate-delivery 测试

当前 `test_worker_duplicate_delivery_is_a_noop` 使用：

```python
lambda *_a, **_k: next(iter([plan, artifact]))
```

每次调用都会重建 iterator，因而始终返回 plan，首次执行可能失败且 Set 数为 0；第二次仍为 0 不能证明重复投递安全。

修正为单一持久 iterator，并明确断言：

- 第一次 delivery 成功；
- Job 为 succeeded；
- 正好一个 Set；
- 第二次 delivery 不调用 provider；
- 仍正好一个 Set，attempt_count 和 AgentRun 数不增加。

同时把旧注释中“plan 是 ToolCall”等过期描述改为与 ADR 002 一致。

## 7. 保持不变

- 不改七类表、migration、删除图、独立 practice worker 或前端共享课节设计。
- 不改 `source_degraded` 完全只读。
- 不新增 ToolCall 名称；白名单仍为 `PracticeEvidenceSearch`、`SubmitPracticeSet`、`SubmitPracticeFeedback`。
- 不运行真实 provider；全部用可计数 fake provider。

## 8. 验证

```powershell
python -m pytest -q apps/api/tests/test_practice_worker.py apps/api/tests/test_practice_api.py apps/api/tests/test_stage4_eval.py
python -m pytest -q apps/api/tests
cd apps/api
python -m stage4_eval.runner --mode offline
cd ../..
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
docker compose config
git status --short --branch
```

## 9. 交回

逐项报告失败 step 的精确例子、owner/lease 参数化矩阵、usage 四种组合、retry/duplicate delivery 测试和全部命令结果。列出完整 git status 后停止。不要重建正式 Compose、OCR、commit、push 或宣布 Slice 完成。

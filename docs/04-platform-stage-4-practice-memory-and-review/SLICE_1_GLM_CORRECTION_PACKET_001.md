# Stage 4 Slice 1 GLM 修正任务包 001

状态：可执行；Codex 独立复核发现已确认缺陷，`source_degraded` 只读语义已于 2026-07-16 获人工确认

用途：在现有 Slice 1 实现候选上进行聚焦修正。不要重写整个功能，不要扩大到后续 Slice。修正完成仍需 Codex 独立复验、OCR 和人工 Chrome Gate。

## 1. 开始前必须读取

1. 根 `AGENTS.md`。
2. `docs/README.md` 与四份产品方向/执行文档。
3. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`。
4. 本 Stage `README.md`、`SLICE_1_GLM_IMPLEMENTATION_PACKET.md` 和 `SLICE_1_FRONTEND_CONCEPT.md`。
5. 已接受并刚完成澄清的 Spec 001、ADR 001/002。
6. 当前 Practice 实现、migration、测试及相邻 Course/Tutor/删除/worker 模式。

开始时记录：

```powershell
git status --short --branch
git diff --stat
```

所有当前 dirty files 都是已知实现或文档成果。不得回滚、覆盖、stash、提交或 push。

## 2. 修正范围

只处理本包列出的引用、预算、最终权威检查、删除 FK、独立 worker、前端合同和对应测试。保留现有公开 API 路径、七类表、题型、评分策略和已通过行为。

不得引入 Mastery、Review Queue、Memory、Skill、MCP、自主多 Agent、认证、计费、新 provider 或真实外部调用。

## 3. High：修复跨检索 citation ledger

### 已确认问题

`services/practice_generation.py::_evidence_search` 每次调用都从 `e1` 开始编号。多个查询返回不同 chunk 时，聚合阶段会产生重复 citation key，并用后一个 chunk 覆盖前一个映射。模型看到的 evidence 与最终落库 citation 可能不一致。

此外 evidence token 在每次 search 内从零累计，未执行整个 Generation Job 的 24K 总上限。

### 必须修正

- citation key 由整次 Generation Job 的统一 ledger 分配，跨 search 单调且唯一。
- 相同 chunk 去重后沿用第一次分配的 key；不同 chunk 永不复用 key。
- evidence 列表、chunk/source 映射和最终 PracticeItemCitation 始终使用同一 key。
- 24K evidence token 是整个 Job 的累计上限，不是每个 search 各 24K。
- 超过总预算时停止加入更多 evidence；不得通过覆盖、截断 artifact 或错误映射提交。
- 保持每次 `top_k <= 5`、最多 3 次 search。

### 必测

- 两次 search 各返回不同 chunk，得到不重复 key，最终每个 key 精确回填原 chunk。
- 两次 search 返回同一 chunk，只保留一条 ledger 记录。
- 多次 search 合计超过 evidence token 上限，不超过总预算。
- artifact 引用第二次 search 的 key 时落库到正确 chunk。

## 4. High：补全预算、usage 与 step 统计

### 已确认问题

生成前的 search-plan provider call 未计入 `provider_calls`、step 和完整 usage；当前预算检查因此与 ADR 002 不一致。

### 必须修正

- search plan、生成、一次修复全部计入 provider call、step、input/output usage 和 wall time。
- search 同样计入 6-step 总预算；实际序列上限为 plan + 最多 3 search + submit + 最多 1 repair。
- 每次 provider call 前后检查取消、wall time、provider call 和 step 预算。
- provider 未报告 token 时保留 `None`/“未报告”语义，不用字符估算伪造 provider usage；如运行时需要估算进行硬预算，必须与报告 usage 分字段，不能混写为 provider token。
- AgentRun/PracticeJob 的 step 和 usage 与真实调用一致。
- Grader 的 evidence 上限使用 settings，不硬编码 `12_000`。

### 必测

- plan call 被计入 provider_calls/steps/usage。
- plan + searches + submit + repair 不超过 6 step。
- 任一预算耗尽不提交 Set/Feedback。
- token 未报告不被公开为估算 token。

## 5. High：最终事务前重新验证权威状态

### 已确认问题

`_job_active` 只覆盖部分 Workspace/Course/Job 状态。生成途中若来源快照失效、Lesson 发布版本改变或 Set/Attempt 删除，最终提交保护不足。

### 必须修正

Generation 最终提交前在同一事务重新验证：

- Workspace active；
- Job 仍由当前 worker 持有且为 `running`，lease 未丢失；
- Course active 且 current active version 仍等于 Job 固定版本；
- Lesson 仍属于固定 Course Version，current published version 仍等于 Job 固定 Lesson Version；
- 所有 `practice_job_sources` 仍与固定 Course Version source snapshot 一致，Document active、current version 相同且 ready；
- 未发生取消或上游删除。

Grading 最终提交前重新验证：

- Job、Attempt、Item、Set 和 Workspace 属于同一 Workspace；
- Attempt 仍是可评分状态且未被删除；
- Set 为 active 且未 `source_degraded`；
- 同一 Attempt 尚无正式 Feedback；
- worker 仍持有 Job 且未取消。

迟到结果必须被丢弃，不创建或复活 Set/Feedback。

### 必测

用 provider fake hook 在调用期间分别改变来源、Lesson current version、Course 状态、Set 状态、Attempt 状态和 Job owner/status，全部不得提交晚到结果。

## 6. High：修复真实 Postgres 删除循环 FK

### 已确认问题

`PracticeJob ↔ PracticeSet` 与 `PracticeJob ↔ PracticeAttempt` 是双向 FK。当前 `cleanup_set` 和 `hard_delete_workspace_practice` 在删除两端前未完整断开循环，SQLite 测试不能证明真实 Postgres 可执行。

### 必须修正

- 在删除依赖实体前，以锁和显式 update 解除双方循环引用：`PracticeSet.practice_job_id`、`PracticeJob.practice_set_id`、`PracticeAttempt.practice_job_id`、`PracticeJob.practice_attempt_id`。
- 然后按 AgentToolCall -> AgentRun -> Feedback -> Attempt -> Item Citation -> Item -> Job Source -> Job -> Set 的可验证顺序删除。
- `delete_attempt` 同样先使 Attempt 不可读/不可评分，取消或解除运行 Job，再删除 trace/Feedback/Job/answer payload。
- `hard_delete_workspace_practice` 使用同样的循环解除和顺序，不能依赖 SQLite 宽松行为。
- cleanup 失败不得恢复 Set 可见性；reconciler 可再次执行且幂等。
- running worker 返回后不能重建已删除 Feedback/Set。

### 必测

- 使用临时真实 Postgres 覆盖：带 Generation Job 的 Set 删除、带 Grading Job/Feedback 的 Set 删除、单 Attempt 删除、Workspace 全量 Practice 删除。
- 每条路径验证所有七类表和 AgentRun/AgentToolCall 无残留。
- 删除中并发晚到 worker 不复活资源。
- cleanup 重复调用安全。

禁止在测试中连接或清空用户现有数据库/volume。

## 7. High：真正拆出独立 practice worker

### 已确认问题

当前 Compose 让原有通用 worker 同时监听 `learn-platform-practice`。单进程仍会被长练习生成占用，未满足 ADR 002 的独立 queue/worker 隔离。

### 必须修正

- 通用 worker 不监听 practice queue。
- 新增独立 `practice-worker` Compose service，只监听配置的 practice queue。
- 沿用同一 API image、数据库、Redis、storage 和必要 provider 环境，不引入新镜像类型或新基础设施。
- health/dependency 和部署说明沿用现有模式，配置中不得硬编码私有地址或凭据。
- `docker compose config` 必须清楚显示两个 worker 的队列边界。

### 必测

- Compose config 验证通用 worker 无 practice queue，practice worker 只含 practice queue。
- practice job 能由 practice worker claim；Tutor job 不会被 practice worker claim。

## 8. Medium：worker lifecycle 与 Attempt 状态

- 增加通过实际 `run_practice_job`/SessionLocal 驱动的 claim、重复投递、retry_wait 到期、queue_failed retry、heartbeat/lease 丢失、cancel_requested -> canceled 测试。
- retryable grading failure 时 Attempt 与 Job 状态保持一致；若 Job 为 `retry_wait`，Attempt 不应继续伪装为普通 `grading`。
- reconciler 只恢复到期/stale Job，不越过 max attempts，不把已取消/已删除资源重新排队。
- failed AgentRun 应保留真实已完成 step/tool 的安全计数；不要因 transaction rollback 统一变成虚假的 step 0。
- 日志仍只记录安全 ID、状态和错误码，不记录题目、答案、rubric、evidence、prompt 或 provider 原错。

## 9. Medium：完成已接受的前端合同

### 必须修正

- 生成表单增加输出语言：沿用课节语言、简体中文、English；请求明确携带选择。
- 生成任务身份显示 Course 名、Lesson 名、题数和状态，不能只显示课节。
- 左侧区域形成可用的 Section/Lesson 目录，而不是仅显示 Section 标题；选中课节是 Reader、Practice 和 Tutor 的共享课节上下文。
- 中间 Practice 与右侧 Practice History 共享当前 Lesson 和当前 Set。右侧选择 Set 必须切换中间完整练习。
- 删除 Attempt/Set、生成成功或状态刷新后，两侧立即一致，不显示 stale 数据。
- 切换 Course、Course Version、Workspace 时重置不属于新 scope 的 lesson/set/job/attempt 状态；不得残留旧 selector value。
- 继续用 CSS 保活正文/Practice/Tutor/History，保留当前 scope 内的题号、草稿、Feedback 展开和滚动状态。
- `source_degraded` 已确认完全只读：历史题目、Attempt、Feedback 可见；引用不可用；生成、提交、重做、重试评分全部禁用并显示清楚原因。
- 不把完整练习移入右侧窄栏，不重做 Workspace 导航或视觉系统。

### 必测

- 增加现有测试栈允许的状态/请求测试：语言 payload、Course/Lesson task identity、右侧 Set 驱动中间、切换 Course/Workspace 清理旧 scope、source-degraded 只读。
- lint/build 必须通过；人工 Chrome smoke 仍由 Codex/用户执行。

## 10. Eval 与回归测试修正

当前 Stage 4 eval 的 case 名称覆盖范围大于实际 probe 深度。不要只保留“通过”的 case 名称。

- 为 citation 多 search、总 evidence 预算、plan call 统计、最终权威突变、真实 Postgres 循环删除、实际 worker claim/retry/cancel 增加能够真实失败的 probes/tests。
- SQLite 适合投影和纯领域检查，但不能代替 Postgres FK/constraint Gate。
- eval report 继续脱敏，不含题目、答案、反馈、rubric、evidence、prompt、路径或 provider 配置。
- 不运行真实 provider；全部使用可计数 fake provider。

## 11. 保持不变且复核即可

- `_item_read/_set_read/_feedback_read` 当前使用显式白名单，继续保留并扩展递归负面键测试。
- Generation `(workspace_id, idempotency_key) + request_hash` 行为保持；补充并发唯一约束冲突转换测试，不泄露数据库异常。
- AgentRun 三属主必须保持“恰一 owner”；migration upgrade/downgrade/upgrade 在临时 Postgres 验证。
- 单选确定性评分且不调用 provider；简答不检索；不引入 fallback 题或固定 50 分。

## 12. 修正后验证

至少运行：

```powershell
python -m pytest -q apps/api/tests/test_practice_domain.py apps/api/tests/test_practice_api.py apps/api/tests/test_stage4_eval.py
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

在不触碰用户现有 volume 的临时 Postgres 上验证 migration `upgrade head -> downgrade -1 -> upgrade head` 和本包删除测试。不要重建/启动正式 Compose，也不要运行真实 provider、OCR、commit 或 push；这些由 Codex 接回后完成。

## 13. 交回格式

报告：

- 逐项对应本包第 3-11 节的修正文件和行为；
- 新增测试名称，特别标明哪些运行于真实 Postgres、哪些仅 SQLite；
- 所有命令的 pass/fail、计数和未运行原因；
- migration、删除循环解除和 Compose worker 边界；
- 前端共享状态的 owner 位置和切换策略；
- 当前完整 `git status --short`；
- 仍需 Codex 复核或人工 Chrome smoke 的风险。

停在这里。不要 OCR、真实 provider、commit、push 或宣布 Slice 1 完成。

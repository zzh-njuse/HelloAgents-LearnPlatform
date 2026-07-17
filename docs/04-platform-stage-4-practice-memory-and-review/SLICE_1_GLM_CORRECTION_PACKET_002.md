# Stage 4 Slice 1 GLM 修正任务包 002

状态：可执行；Correction 001 接回后的 Codex 独立复核补充

用途：只关闭 Correction 001 遗留的运行所有权、trace 计数、usage、retry claim 和共享课节上下文问题。不要重新设计 Practice 或扩大产品范围。

## 1. 开始前

完整读取根 `AGENTS.md`、仓库指导文档、GLM 交接工作流、本 Stage README、Spec 001、ADR 001/002、前端概念、原实现任务包和 Correction 001。

检查并保留全部 dirty files：

```powershell
git status --short --branch
git diff --stat
```

不得回滚、stash、commit、push、运行真实 provider 或 OCR。

## 2. High：最终提交必须验证 worker owner 与 lease

### 遗留问题

`_assert_generation_authority` / `_assert_grading_authority` 只检查 Job 为 `running`，没有确认仍由开始执行的 worker 持有，也没有确认 lease 仍有效。若 reconciler 重置并由新 worker claim，旧 worker可能在 heartbeat 下一次发现 owner 丢失前提交结果。

### 修正要求

- `run_practice_job` claim 后把不可变的 `worker_id` 显式传入 generation/grading 执行边界，或采用等价且可测试的 owner token。
- 每次 provider 调用前后和最终事务前必须同时确认：
  - Job 仍为 `running`；
  - `job.worker_id == expected_worker_id`；
  - `lease_expires_at` 存在且晚于当前数据库/UTC 时间；
  - heartbeat 线程未报告 lease lost。
- 测试直接调用执行函数时可以显式建立测试 owner/lease，不得通过“owner 为 None 就跳过全部生产检查”让正式 worker 路径失去保障。
- owner 改变、lease 过期或 status 被 reconciler 重置时统一丢弃迟到结果，不提交 Set/Feedback。

### 必测矩阵

- generation provider 返回前后 worker_id 被替换；
- generation lease 在最终提交前过期；
- grading worker_id 被替换；
- grading lease 过期；
- Lesson current version、Course current version、source snapshot、Set lifecycle、Attempt status 分别在 provider 期间改变；
- 上述每项均断言无新 Set/Feedback，旧 worker 不覆盖新 owner 状态。

## 3. High：step、provider call 与 tool trace 必须一致

### 遗留问题

- `call()` 当前为 provider 返回先写一条 `SubmitPracticeSet/SubmitPracticeFeedback` tool call，artifact 校验后又写一条成功记录，同一次提交被重复计数。
- `ordinal += 1` 的最终“commit record”使 `AgentRun.step_count` 高于真实 6-step 预算；eval 甚至以 `max_steps + 1` 放行。
- `PlanPracticeSearch` 被写成 AgentToolCall，但 ADR 002 的 Exercise Author 工具白名单只有 `PracticeEvidenceSearch` 与 `SubmitPracticeSet`。Plan 是内部 provider step，不是额外产品工具。

### 修正要求

- `AgentRun.step_count` 精确等于实际受控 step：plan provider call + searches + submit provider calls；始终 `<= 6`。
- provider call 与 tool call 分开计数：plan 计 provider/step/usage，但不伪装成 ToolCall。
- Exercise Author 的 AgentToolCall 名称只能是 `PracticeEvidenceSearch`、`SubmitPracticeSet`。
- Answer Grader 若记录结构化提交，名称只能是 `SubmitPracticeFeedback`。
- 每次结构化提交尝试只产生一条 tool trace：校验成功记 succeeded，校验失败记 failed；一次 repair 是第二次提交尝试，不重复添加“commit record”。
- `AgentToolCall.ordinal` 对应真实全局 step ordinal，可以不连续，但必须稳定递增且无重复。
- failed AgentRun 的 step_count 使用真实 step 数，不等同于 tool call 数，也不能固定为 0。

### 必测

- plan + 1 search + 1 valid submit：step_count=3，tool names 仅 search/submit，各一条。
- plan + 3 search + invalid submit + repair：step_count=6，不出现第 7 步。
- grader 首次成功：step_count=1、一个 submit trace。
- grader repair：step_count=2、两次 submit trace，先 failed 后 succeeded。
- eval 不得使用 `max_steps + 1` 容忍错误计数。

## 4. Medium：缺失 token usage 必须整体显示“未报告”

### 遗留问题

当前只对有值的调用求和。如果多个 provider call 中任一次缺少 input/output usage，最终仍可能返回其他调用的部分合计，让用户误以为是完整总量。

### 修正要求

- 分别追踪 input/output usage 是否在本次 run 的每个 provider call 都有报告。
- 任一 call 缺少某一方向 usage，则该 run/job 对应总字段为 `None`，不得公开部分和。
- hard budget 可以使用独立内部估算，但不得写入 provider usage 字段或安全运行摘要。
- 全部 call 都报告时才保存精确总和。

### 必测

- 全部报告、全部缺失、只有 plan 缺失、只有 repair 缺失四种组合。

## 5. Medium：`retry_wait` 不得提前 claim

### 遗留问题

`run_practice_job` claim 条件允许任何 `retry_wait` Job 立即领取，没有验证 `next_attempt_at <= now`。重复或异常 RQ delivery 可绕过退避时间。

### 修正要求

- claim 只允许 `queued`，或 `retry_wait` 且 `next_attempt_at` 已到期。
- 未到期 delivery 必须无副作用返回，不增加 attempt_count、不改变 owner/status。
- reconciler 仍只 enqueue 已到期 retry，且达到最大尝试次数后不再恢复。

### 必测

- 未到期 retry_wait 不 claim；到期后正常 claim；重复 delivery 只有一个 owner。

## 6. Medium：补全 `source_degraded` 与 deleting reconciler 测试

- API 测试必须明确断言降级历史 Set 仍可读，但单选和简答的新 Attempt 均返回 `source_snapshot_stale`，评分 Job retry 也不得恢复。
- Web 必须保留删除 Attempt/Set 的能力；“只读”只禁止生成、作答、重做和重新评分，不剥夺删除权。
- 增加 deleting Set reconciler 测试：cleanup enqueue 失败后保持 deleting，达到 stale 条件后重新 enqueue，成功 cleanup 后七类表和 trace 无残留。
- 真实 Postgres 删除测试继续使用临时数据库；不得连接、清空或迁移用户正式数据库。

## 7. Medium：左侧课节必须成为共享上下文

### 已接受合同

左侧当前课节是 Reader、lesson-scope Tutor、Practice 与练习记录的共享上下文。course-scope Tutor 仍显示整门课程历史，不受课节筛选限制。

### 修正要求

- 将 `practiceLessonId` 提升/重命名为含义明确的共享 current lesson state。
- 左侧点击课节必须对正文产生真实导航效果：聚焦/滚动到所选课节或只展示所选课节；不能只改变 Practice selector。
- `PracticePanel`、`PracticeHistoryPanel` 与 Tutor 的 lesson scope 使用同一受控 lesson id。
- Tutor 可以保留课节 selector，但它必须读写同一共享 state；不是第二套独立选择。
- Tutor 切到 course scope 时不清空共享课节；切回 lesson scope 继续使用当前共享课节。
- 切换 Course/Course Version/Workspace 时重置到新 scope 的首个已发布课节，并清理旧 Set；当前 scope 内正文/练习/右栏切换仍保留草稿和题号。

### 必测

- 左侧、Practice selector、Tutor selector 任一处切课节，另外两处同步。
- lesson-scope Tutor 历史只显示共享 Lesson Version；course scope 仍只显示 course turns。
- 切 Course/Workspace 无旧课节、Set 或 Tutor lesson filter 残留。

## 8. 保持已经验证的修正

不要破坏以下已通过结果：

- job-wide citation ledger 和总 evidence budget；
- Postgres 循环 FK 解除与删除顺序；
- 独立 `practice-worker` Compose service；
- `source_degraded` 完全只读；
- 输出语言、Course/Lesson 任务身份和 Practice/History Set 联动；
- 答案投影白名单、幂等冲突、单选确定性评分和 Grader 无检索。

## 9. 验证

```powershell
python -m pytest -q apps/api/tests/test_practice_domain.py apps/api/tests/test_practice_api.py apps/api/tests/test_practice_worker.py apps/api/tests/test_practice_deletion_postgres.py apps/api/tests/test_stage4_eval.py
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

不重建或启动正式 Compose；Codex 会在接回后执行 migration、build/up/ready/Web/practice worker smoke。

## 10. 交回

逐节说明修正文件、新增测试、实际 step/tool/usage 例子、worker owner/lease 保护、共享课节 state owner 和全部命令结果。列出完整 git status，然后停止。不要 OCR、commit、push 或宣布 Slice 1 完成。

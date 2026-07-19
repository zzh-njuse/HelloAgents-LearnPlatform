# Stage 4 Slice 3 GLM 修正任务包 002

状态：待 GLM 执行
日期：2026-07-19
依据：已接受的 Spec 003、ADR 005、原实现任务包和修正任务包 001

## 1. 背景

Codex 已独立复验修正任务包 001：51 个 Tutor/readiness focused tests、Web lint/build 和 `docker compose config` 通过。但代码复核确认仍有两个运行时缺陷、一个真实并发权威缺口，以及数项任务包 001 明确要求但未覆盖的测试。修正 001 仍是候选实现，Slice 3 尚未通过 Gate。

本包只关闭这些剩余缺口。不要改变产品设计，不增加第二种 Skill、模式切换、MCP、多 Agent 或新的学习事实；禁止固定问题、关键词、fixture 和 smoke 答案硬编码。

## 2. 开始前

完整读取根 `AGENTS.md` 要求的指导文档、Stage 4 README、Spec 003、ADR 005、`SLICE_3_GLM_IMPLEMENTATION_PACKET.md`、修正任务包 001 和本任务包。先检查 `git status --short --branch`。

现有 Slice 3 dirty diff 是已知候选实现。不得读取、清理、回滚或提交 `.tmp/`、`artifacts/` 和其他未知改动。

## 3. 必须修正

### 3.1 P0：自动 retry_wait 目前可能无限重试

当前 `tutor_workers._finish_failed_turn` 使用 `turn.attempt_number <= ingestion_max_attempts` 判断自动重试。`attempt_number` 表示用户对同一逻辑 Turn 的显式 retry 版本，自动 `retry_wait` claim 不会增加它，因此首次 Turn 的可重试错误可以无限进入 `retry_wait`。

修正要求：

- 自动 delivery attempt 必须有独立、可权威计算的次数，不能复用用户可见的 `attempt_number`。
- 优先在当前 Turn 下按已持久化 AgentRun 数量计算：本次失败计入后，仅当总 delivery attempt 严格小于 `ingestion_max_attempts` 才进入 `retry_wait`；达到上限稳定进入 failed。
- 如果选择新增数据库计数字段，必须补 migration、ORM、claim 原子递增和 Postgres 验证；不要仅为方便随意扩 schema。无 schema 方案能可靠满足时优先无 schema 方案。
- 用户显式 retry 创建的新 TutorTurn，自动重试预算重新开始；原 Turn 的失败 AgentRun 保留。
- `generation_provider_unavailable` 与 `invalid_agent_artifact` 可进行有界自动重试；`teaching_skill_unavailable`、`source_snapshot_stale`、`generation_canceled` 保持终态，不自动循环。

测试必须证明：`ingestion_max_attempts=3` 时恰好最多执行 3 次 delivery；第 1/2 次失败进入 retry_wait，第 3 次失败进入 failed；后续重复 delivery 不再调用 provider或新增 AgentRun；显式 retry 的新 Turn 重新拥有自己的 3 次预算。

### 3.2 P0：真实跨事务最终权威检查不能使用缓存旧对象

当前 `_assert_final_authority` 只 `db.refresh(turn)`，随后对 Session、Course、Lesson、LessonVersion、SourceDocument 和 DocumentVersion 使用 `db.get()`。这些对象已可能存在于 identity map；若另一个 Postgres transaction 在 provider 运行期间提交删除、换版或降级，`db.get()` 可以返回缓存旧状态，现有“同 session mutation”单测无法证明真实并发可见性。

修正要求：

- 最终检查必须从数据库重新读取权威状态，使用明确的 `refresh`、`populate_existing` 或合适的 `SELECT ... FOR UPDATE`，不得依赖 identity-map 缓存。
- 检查与成功写入处于同一 transaction，并使用与删除/发布路径兼容的稳定锁顺序，避免在检查后、commit 前再次被并发改变。
- Turn owner/lease/status、Workspace、Session、Course active version、lesson scope 的 Lesson/current published version，以及 ledger 的 Document/current ready version全部适用。
- owner/lease/cancel/session/workspace 失效映射 `generation_canceled`；Course/Lesson/source snapshot 变化映射 `source_snapshot_stale`，不得把来源降级伪装成用户取消。
- 正常 answer、repair answer、plan-only limitation、历史 baseline success 全部走同一最终权威边界。

测试要求：

- 补齐任务包 001 未实现的 `course_changed` 和 lesson-scope `lesson_changed` 变体。
- 至少增加一个能证明 identity-map 旧对象被强制刷新的测试：先在执行 session 加载对象，再由独立 SQLAlchemy Session 提交变更，最终检查必须观察到新状态。SQLite 锁限制无法表达的真实并发场景必须进入 Postgres-only 测试。
- source degraded 断言稳定得到 `source_snapshot_stale`，且无 answer/citation/succeeded。

### 3.3 P1：search 失败的 step_count 少算一步

当前 Skill 和 baseline 都在 `_search()` 返回后才执行 `step += 1`。检索调用若抛错，失败 AgentRun 不会记录已经开始的 search step，与修正任务包 001 的“调用前计步”合同不符。

修正要求：

- provider 和 search 都必须在 budget check 通过后、实际调用前增加 step_count 并 `flush()`。
- ToolCall 仍只在检索产生可记录结果后写入；失败 step_count 不得由 ToolCall 数反推。
- provider 首次失败为 step 1；plan 成功后首次 search 失败为 step 2；plan + search + answer + repair 的语义保持精确。

### 3.4 P1：是否有“可用状态”必须以预算后实际注入为准

当前 `has_state = learning["available"]` 在预算裁剪前计算。若所有候选因超长标题/预算被移除，代码仍认为有状态，跳过诚实 limitation，并可能向 answer provider 发送空 projection。

修正要求：

- 先完成预算化 injection，再根据实际注入的 targets/memories/completions 判断 `injected_state_available`。
- plan prompt 可以知道“存在候选状态”，但最终 `learning_state_injected`、无证据 limitation、校准和 actual-use count 必须依据实际注入内容。
- 不允许空 projection 被宣称为已使用个性化状态。
- 预算选择不能让大量 resolved/no-memory target 抢占全部预算、饿死更相关的 active Memory 或 confirmed/provisional weakness；落实任务包 001 的优先级并增加反例。
- 预算估算继续允许明确记录的保守字符法，但要计入实际序列化结构的固定开销；至少断言最终发送的 learning-state JSON 估算不超过约 800 tokens，而不只是某条长 Memory 未出现。

### 3.5 P1：补齐任务包 001 明确要求的测试矩阵

修正 001 报告声称完整关闭，但以下测试仍缺失，必须补齐：

- token usage：answer 首次无效、repair 成功时，plan/answer/repair 任一调用分别缺 input 或 output 的逐维聚合。
- failed trace：plan provider 首次失败；plan 成功后 search 抛错；最终 owner/lease/source authority 拒绝时的真实 step_count 和 usage。
- scope isolation：另一个 Workspace/Course/LessonVersion 的 Memory、Weakness、Mastery 和 Completion 均不得进入选择、prompt、trace count 或公开结果。
- final authority：Course active version changed、lesson current published version changed、source degraded 的准确错误码。
- readiness：metadata/hash 篡改和文件缺失均 degraded，detail 不含路径/hash/prompt。

测试不得用同 session 对象 mutation 冒充所有跨事务语义，也不得只断言“抛了 ValueError”；需要断言稳定 error code、无成功产物和真实 trace。

## 4. 允许修改范围

可修改：

- `apps/api/learn_platform_api/services/tutor_generation.py`
- `apps/api/learn_platform_api/tutor_workers.py`
- `apps/api/learn_platform_api/db/models.py` 和 migration（仅当 3.1 确实需要）
- `apps/api/tests/test_tutor_skill.py`
- 必要的相邻 Tutor worker/readiness/Postgres tests
- 必要的 Stage 3 paired eval 调用适配

除非测试证明需要，不要继续改 Web、Skill 正文、Slice 2 学习投影或其他产品模块。

## 5. 验证

至少真实运行：

```powershell
cd apps/api
python -m pytest -q tests/test_tutor_api.py tests/test_tutor_skill.py tests/test_readiness.py
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

Docker Desktop 已运行时再执行 migration、Postgres-only authority/retry tests、`/ready`、Web 200 和脱敏业务 smoke；否则如实报告未运行。不要调用真实 provider 或 OCR。

## 6. 交回格式与停止点

报告必须逐项说明 3.1-3.5 的实现、精确测试名称/结果、自动重试三次矩阵、跨事务权威验证、错误码、失败 step/token、全量验证和未运行项，并附完整 `git status --short`。

完成后停止：不要 OCR、不要 commit、不要 push、不要宣布 Slice 3 完成。

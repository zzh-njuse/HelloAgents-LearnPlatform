# Stage 4 Slice 2 GLM 修正任务包 001

状态：待执行；Codex 独立复核发现合同级缺口，当前实现候选不得进入 OCR 或人工 Gate

日期：2026-07-17

## 1. 开始前

完整重读根 `AGENTS.md`、四份产品/执行指导文档、`docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`、Stage 4 README、Spec 002、ADR 003/004、Slice 2 前端概念、原实现任务包和本修正包。

运行：

```powershell
git status --short --branch
git diff --stat
```

保留当前全部 dirty files。不得回滚、stash、commit 或 push；不得运行真实 provider 或 OCR。

## 2. Codex 独立复验事实

- Slice 2 focused：17 passed。
- API 全量：156 passed。
- Stage 4 offline eval：35/35 hard gates，3 observational。
- Web lint 通过；production build 通过。
- `docker compose config --quiet` 通过。

这些结果只证明现有测试矩阵通过。以下问题由代码合同审查发现，现有测试没有覆盖，不得用“全绿”排除。

## 3. High：Feedback 与投影不是同一事务

当前 `services/practice.py::_try_project_learning` 在 Feedback 已 commit 后另开 best-effort 投影，并吞掉所有异常；评分 worker 也在正式 grading commit 后才调用投影。若投影失败，Feedback 已存在但 Event/Signal 缺失，而 `recompute_workspace` 只重放已有 Signal，不会从 Feedback 恢复，学习事实会永久漏记。

必须修正：

- 单选与简答正式 Feedback、Learning Event、Signal 和受影响 target 投影在同一权威事务提交。
- 不允许 `except Exception: rollback/pass` 把合同失败隐藏成成功。
- 重复 worker delivery 仍由 Feedback/Event/Signal 唯一约束成为 no-op。
- 若保留全量重算，必须能从有效 Attempt/Feedback 权威事实重新构建 Event/Signal，而不是依赖可能缺失的派生 Event/Signal。
- 增加 provider/grading 成功但投影抛错、事务整体回滚或可恢复重算的测试。

## 4. High：Attempt/Set/Course/Workspace 删除顺序违反新 FK

当前 Attempt 和 Set 删除先删 Feedback/Attempt，之后才尝试清理 Learning Event；真实 Postgres 上 `learning_events` 对 Attempt/Feedback 的 FK 会阻断删除。Set worker 在 `cleanup_set` commit 后再查询已删除 Item，无法找到清理范围。Course/Workspace 删除又以 broad `except` 吞掉学习清理失败，可能返回成功但残留派生事实。

必须修正：

- 删除前先物化受影响 target/event/item/attempt IDs。
- 顺序至少满足 MemorySource -> Signal -> Event -> Feedback/Attempt，并重算仍存在的 target。
- Set cleanup 在删除 Item/Attempt 前完成学习事实清理，不能事后空查。
- Course/Workspace 删除不得吞掉学习清理异常并继续报告成功。
- 延续现有权威 hiding/deleting 与晚到结果规则。
- 扩展真实 Postgres 删除测试，覆盖存在 confirmed Memory、Revision、Source、Review Action 时的 Attempt/Set/Course/Workspace 删除。

## 5. High：全量重算破坏用户管理的 Memory

当前 `recompute_workspace` 删除 Workspace 的全部 Memory、Revision、Source、Weakness 和 Review，再按默认模板重建。这会丢失用户编辑的 `display_text`、paused/archived 状态、revision 历史和重新确认信息，也可能让归档 Memory 复活。

必须修正：

- Event/Signal/Mastery/Weakness/Review 的可重算不等于删除用户管理事实。
- 重算必须保留 Memory ID、用户编辑文本、paused/archived、revision 和 suppression 水位。
- 只根据新投影更新允许自动变化的字段，如 active -> needs_review、source links、last_supported_at。
- archived/paused 不得因重算恢复 active；用户删除后的旧证据不得复活。
- 增加编辑、暂停、归档、删除后分别执行两次 recompute 的回归测试。

## 6. High：新题 target mapping 与简答信号不符合 ADR 003

当前 `ensure_item_target_mapping` 把所有未映射 Item 统一映射到 `lesson_overall` 且 `criterion_key=None`。`_generate_signals_for_attempt` 因此会把简答走入 fallback，按 `correct/not-correct` 生成 weight=1.0、`is_ai_derived=0` 的确定性信号，丢失 rubric partial 与 AI 0.6 权重。新 Exercise artifact 也没有实现 target/criterion mapping。

必须修正：

- 新生成 Practice artifact 明确携带合法 target key；简答 rubric criterion 映射 target key。
- validator 拒绝未知、跨 Lesson Version 和空 target mapping。
- 只有 Slice 1 旧 Item 才使用 `lesson_overall` fallback。
- 旧简答即使只有 `lesson_overall`，也必须从 criterion_results 按 rubric weight 聚合，并使用 AI weight=0.6，不得冒充确定性单选。
- 增加 full/partial/none、多 criterion 同 target、旧 Item fallback 和未知 target 测试。

## 7. High：migration backfill 实际没有建立 Target

Migration 0017 只从 `learning_targets` join `lesson_overall` 后插入 Item mapping，但 migration 本身没有为已有 Lesson Version 创建任何 Target，因此正常升级时 join 为空，旧 Practice Item 不会完成 backfill。`md5(pi.id::text)` 本身也不能替代对完整迁移结果、重复升级和 UUID/ID 格式的验证。

必须修正：

- migration 先为所有已有 Lesson Version 确定性建立 `objective_1..N` 与 `lesson_overall`，再 backfill Item。
- JSON learning objectives 的 Postgres 读取必须真实验证；无法可靠解析时至少建立 `lesson_overall`，不能留空。
- backfill ID 必须稳定、合法且无碰撞；upgrade/downgrade/upgrade 结果一致。
- 增加已有 Course/Lesson/Practice 数据的临时 Postgres migration integration test，不得只用 `Base.metadata.create_all`。

## 8. High：Memory 来源、过期和 Review 状态机未落地

当前自动创建 Memory 没有写任何 `LearningMemorySource`，所以 UI 永远显示来源 0 条，删除最后 source、source degraded 和证据追踪合同无法实现。`MEMORY_EXPIRY_DAYS` 只声明未使用；90 天转 needs_review 没有执行。dismiss 后新负向证据不重开 Review，Weakness 也没有进入 dismissed；resolve 统计包含 Weakness 产生之前的正向信号，可能刚创建就解决。

必须修正：

- confirmed Memory 关联支持它的有效负向 Learning Event；增量投影与重算维护 Source links。
- 删除最后 source 时按 ADR 硬删除或按明确合同处理；不得显示虚假 source_count。
- 90 天无支持证据、source degraded、Lesson 新版本和相反证据按 ADR 转 needs_review，并停止 Tutor 使用。
- dismiss 更新相应 Weakness/Review 状态；新的负向 event 重开并递增 `reopen_count`。
- resolved 只统计 Weakness 创建之后的两个不同 Item 正向验证。
- `reconfirm` 不得把用户确认时间伪装成新的证据 `last_supported_at`。

## 9. High：Tutor Memory scope 会跨课程外发

当前 `_load_memory_context` 先取 Workspace 最近 5 条，再按 Course 过滤；若没有 Course 命中，会 fallback 到 Workspace-wide Memory。它没有 Lesson 过滤，也可能因为先 limit 而漏掉真正相关 Memory。这违反“仅当前 Workspace/Course/Lesson 精确关联”，属于外发范围错误。

必须修正：

- 在 SQL 查询中同时限定 Workspace、active、当前 Course，并在 lesson scope 时限定当前 Lesson/Lesson Version。
- 没有精确匹配时返回空，不得 fallback 到 Workspace-wide。
- 先过滤再排序/limit 5。
- 约 600 token 上限采用项目现有 token 估算工具或明确保守算法；不得仅依赖随语言变化很大的字符数而无测试。
- AgentRun/安全 trace 只记录 count 和 hashed IDs，不记录 Memory 文本。
- 增加两个 Workspace、两个 Course、两个 Lesson、policy off、needs_review/paused 和超过 5 条的负面外发测试。

## 10. High：重算 Job 没有完整 lease/取消权威

当前 `run_learning_recompute` 只有一次 claim，没有 heartbeat、取消处理、owner/lease 最终重检或 policy revision 重检；重算先 commit 业务投影，再另行写 succeeded，lease 被替换或 Workspace 删除时仍可能提交。API 又自行生成随机 idempotency key，没有使用请求 `Idempotency-Key`，也没有 cancel/retry 路由。

必须修正：

- 沿用现有 practice worker 的 claim、heartbeat、lease、cancel、retry 和 reconciler 模式，不得只借用队列名称。
- 最终业务提交与 owner/lease/Workspace/policy revision 权威重检在同一事务。
- API 接受并校验 `Idempotency-Key` + canonical request hash；实现任务包要求的 cancel/retry 行为。
- 重复 delivery、retry_wait 未到期、owner replaced、lease expired、Workspace deleting 和 policy changed 均有测试。

## 11. High：前端未实现已接受的信息架构

当前 Web 仅在顶层增加一个简单 `ReviewMemoryPanel` 列表。缺少已接受的 Workspace 紧凑“今日复习”入口、接近整页的三栏 focus page、队列筛选/当前项/推荐依据、Reader 当前 Lesson 摘要、Tutor 本次使用 N 条状态、打开课节/反馈/验证练习、重算 Job 状态和完整响应式矩阵。API 错误又被逐项 `.catch(() => [])` 转为空状态，真实失败会伪装成“暂无内容”。

必须修正：

- 忠实实现 `SLICE_2_FRONTEND_CONCEPT.md`，不要用普通卡片列表替代已接受布局。
- Workspace 入口紧凑；完整操作进入 focus view并可返回且保留 Reader 状态。
- 桌面三栏、中等两栏/抽屉、移动单栏；长文本无溢出。
- 显示推荐原因、AI/确定性构成、证据数、最后验证时间和安全位置。
- Reader 只显示当前 Lesson 摘要；Tutor 显示本次拟使用 Memory 数量和管理入口。
- loading/empty/error/provisional/confirmed/awaiting_validation/resolved/source_degraded/job running/failed 均真实可见。
- 不吞 API 错误冒充空列表。
- 补充前端状态/scope 测试；最终仍需 Chrome 人工 smoke。

## 12. 其他必须修正

- Mastery 的“distinct Attempt”不能用 `practice_item_id` 计数；重复作答是不同 Attempt，但 Weakness 确认仍要求不同 Item。必要时通过 Learning Event 关联 Attempt 计数。
- `learning_memories` 必须有数据库级并发唯一策略，保证同 target 不产生多个当前 Memory；仅应用层先查不足以抵抗并发。
- API 对不存在 Workspace 必须稳定 404；GET policy 不得尝试插入孤儿 policy 后返回 500。
- Review/status/filter 使用枚举与长度/数量上限；安全响应继续排除 projection score、答案、rubric、feedback、prompt、evidence 和 provider 配置。

## 13. 验证要求

完成修复后运行并逐条报告：

```powershell
python -m pytest -q apps/api/tests -k "learning or mastery or review or memory or practice or delete or reconciler"
python -m pytest -q apps/api/tests
cd apps/api
python -m stage4_eval.runner --mode offline
cd ../web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
docker compose config
```

必须在临时真实 Postgres 验证 migration 与新增删除图。若 Docker 环境允许，重建 Compose 后验证 migration head、`/ready`、Web 200、practice worker 与 learning recompute worker；不得删除用户现有 volume。

## 14. 交回格式

- 按第 3-12 节逐项说明修改文件、实现语义和测试名称。
- 单列仍未实现或与合同冲突的部分，不得以“后续优化”隐藏 High。
- 给出每条命令真实结果和测试计数。
- 给出完整 `git status --short`。
- 停止在实现交回：不运行真实 OCR/provider，不 commit/push，不宣布 Slice 2 完成。

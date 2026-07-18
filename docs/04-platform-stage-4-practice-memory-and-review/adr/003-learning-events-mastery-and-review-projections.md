# ADR 003：Learning Event、掌握度与复习投影权威

状态：已于 2026-07-17 通过人工 Gate

日期：2026-07-17

## 背景

Slice 1 提供不可变 Attempt/Feedback，但 Practice Item 尚无稳定学习目标映射。Prototype 以问题文本为 topic、用单次分数或固定加权平均更新 JSON mastery，无法满足版本、删除、重算、workspace 隔离和抗单次污染要求。

## 决策

Postgres 保存原始学习事件、确定性信号和可重算投影。Mastery/Weakness/Review 不调用 LLM，不以 Qdrant、Redis、本地 JSON 或 Neo4j 为权威。

## 数据模型

| 表 | 关键字段与约束 |
|---|---|
| `learning_targets` | workspace/course/course_version/lesson/lesson_version、`target_key`、title、kind=`objective|lesson_overall`；版本内 key 唯一 |
| `practice_item_targets` | practice_item、target、可选 `criterion_key`；组合唯一，全部归属必须同 workspace/version |
| `learning_events` | event_type=`practice_result`、workspace、source_attempt/feedback、occurred_at；对 feedback 唯一 |
| `mastery_signals` | event、target、outcome=`positive|partial|negative`、value、weight、source_kind、is_ai_derived；event+target 唯一 |
| `mastery_states` | target 唯一、band、evidence_count、distinct_set_count、projection_score、last_evidence_at、revision |
| `weaknesses` | target 唯一、status=`provisional|confirmed|resolved|dismissed`、reason_code、first/last_negative_event、`memory_suppressed_at`、revision |
| `review_items` | weakness 唯一、status、due_at、last_action_at、reopen_count、reason snapshot |
| `review_actions` | review_item、action、可选 snooze_until、created_at；append-only |
| `learning_projection_jobs` | workspace、status、idempotency/request hash、attempt/lease/error/时间字段 |

`projection_score` 是内部确定性计算值，只用于分档和测试；公开 API 不把它包装为精确用户能力百分比。

## Target 身份

- 每个 Lesson Version 从 `learning_objectives` 建立 `objective_1..N`。
- 另建 `lesson_overall`，仅用于没有细粒度映射的旧数据或整体题。
- 新 Exercise artifact 为 Item 声明 target key；简答 rubric criterion 可声明 target key。
- 关联写入前验证 target 属于相同 Lesson Version 和 Workspace。
- Lesson 新版本创建新 target，不自动跨版本合并；旧状态保留为历史。

## 信号生成

一个 Attempt 对同一 target 最多生成一个聚合 signal：

| 来源 | value | weight | AI |
|---|---:|---:|---|
| 单选 correct | 1.0 | 1.0 | false |
| 单选 incorrect | 0.0 | 1.0 | false |
| 简答 criterion full | 1.0 | 0.6 | true |
| 简答 criterion partial | 0.5 | 0.6 | true |
| 简答 criterion none | 0.0 | 0.6 | true |

多个 criterion 指向同一 target 时先按 rubric weight 求 value 加权平均，再应用 0.6 AI weight。`ungradable`、失败、取消、未答题和没有 Feedback 的 Attempt 不生成 signal。

## 投影算法

对 target 读取最近 10 个有效 Attempt signal，按时间倒序但不进行随时间静默衰减：

```text
score = (1 + Σ(value × weight)) / (2 + Σweight)
```

使用 Beta(1,1) 先验避免第一次结果成为 0 或 100。分档：

- 少于 2 个 distinct Attempt 或总 weight < 1.5：`insufficient`；
- 达到证据门槛且 score < 0.55：`needs_review`；
- 其他未满足 secure 条件：`developing`；
- score >= 0.80、至少 3 个 distinct Attempt、至少 2 个 distinct Practice Set：`secure`。

阈值是第一版可测试产品常量，后续调整必须版本化 projection policy 并全量重算，不能静默改变历史含义。

## Weakness 与 Review

- 第一个 value < 0.5 的 signal 创建 `provisional` Weakness 和 due Review Item。
- 至少两个不同 Practice Item 的负向 signal，且 band=`needs_review`，转为 `confirmed`。
- dismiss 不删除信号；记录 action 并关闭当前 item。
- dismiss 后出现新的负向 event，Review Item 重开并递增 `reopen_count`。
- Weakness 创建后出现至少两个不同 Item 的 value >= 0.8 signal，且 band=`secure`，转为 `resolved`。
- reviewed action 只把 Review Item 改为 `awaiting_validation`，默认 `due_at=now+3d`，不写 mastery signal。

## 事务、幂等与重算

- Feedback 成功提交的同一事务中创建唯一 Learning Event、Signal 并重算受影响 target。
- 重复 worker delivery 依赖 feedback/event 唯一约束成为 no-op。
- Attempt 删除前锁定其 target，删除 event/signal 后在同一事务重算；无证据的 state/weakness/review 删除。
- 单 target 重算同步完成；Workspace 全量重算创建权威 Job，经现有 practice queue 投递给 practice worker。
- Job 使用现有 claim/lease/heartbeat/retry/cancel/reconciler 模式；不调用 provider，token usage 必须为 null。
- 晚到 rebuild 在最终提交前重检 workspace、owner、lease 和 policy revision。

## 删除

- target 派生事实跟随 Course/Workspace 硬删除。
- Attempt/Set 删除触发受影响 target 重算，不保留已删除答案或 feedback 内容副本。
- source degraded 不删除历史事件，但 state API 标注 `source_degraded`；该来源不能产生新 signal。
- Review reason snapshot 只含安全 target 名称、event 类型和时间，不复制答案、feedback 或证据正文。

## 影响

优点：投影可解释、可重算、成本稳定；一次错误不会变成长期画像；删除能撤回派生状态。

代价：需要扩展 Exercise artifact 的 target 映射；旧数据只能获得 lesson-level 粗粒度状态；阈值策略需要版本管理。

## 未采用方案

- 直接复用 `UserModel` JSON 和 70/30 平均：缺少身份、来源与重算。
- LLM 读取历史答案后生成 mastery：成本、漂移、隐私和不可重算风险过高。
- 每日时间衰减 mastery：会在没有新事实时静默改变状态，并需要定时任务。
- 新增独立 learning worker：第一版确定性计算不足以证明额外部署服务的收益。

## 生效条件

Spec 002、ADR 003/004、前端概念与阈值已于 2026-07-17 获得人工接受，可以生成 Slice 2 GLM 实现任务包。

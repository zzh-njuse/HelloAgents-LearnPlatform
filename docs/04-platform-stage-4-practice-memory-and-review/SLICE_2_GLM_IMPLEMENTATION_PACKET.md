# Stage 4 Slice 2 GLM 实现任务包

状态：可执行；Spec 002、ADR 003/004 与前端概念已于 2026-07-17 通过人工 Gate

用途：交给配置 GLM 的 Claude Code 或同类 coding agent 顺序实现。GLM 负责正式编码、测试和实现报告；Codex 保留需求解释、跨模块合同复核、OCR、完整复验、人工 smoke 协调、阶段总结和提交决策。

## 1. 开始前必须完整读取

不得只依赖本任务包。按顺序读取：

1. 根 `AGENTS.md`。
2. `docs/README.md`。
3. `docs/LEARNING_AGENT_BLUEPRINT.md`。
4. `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`。
5. `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`。
6. `docs/AGENT_COLLABORATION_PLAYBOOK.md`。
7. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`。
8. `docs/03-platform-stage-3-chapter-learning-and-tutor/STAGE_3_SUMMARY.md`。
9. 本目录 `README.md`、`STAGE_4_INPUTS.md`、`STAGE_4_SLICE_PLAN.md`、`SLICE_1_SUMMARY.md` 和 `SLICE_2_INPUTS.md`。
10. `SLICE_2_MEMORY_FACT_INVENTORY.md` 与 `SLICE_2_FRONTEND_CONCEPT.md`。
11. 已接受的 `specs/002-explainable-mastery-review-and-managed-memory.md`。
12. 已接受的 `adr/003-learning-events-mastery-and-review-projections.md`。
13. 已接受的 `adr/004-user-managed-learning-memory.md`。
14. Slice 1 的 Spec 001、ADR 001/002，以及 `apps/api`、`apps/web`、`academic_companion` 相邻实现和测试。

开始时运行并记录：

```powershell
git status --short --branch
git diff --stat
```

当前未提交的 Slice 2 Spec、ADR、事实盘点、前端概念、索引和本任务包是 Codex 已完成并经人工接受的文档成果。保留全部已有 dirty files，不得回滚、覆盖、stash 或清理。

## 2. 总目标

把 Slice 1 的可信作答事实形成可解释、可重算、可删除的学习闭环：

```text
已评分 Attempt
  -> Learning Event / target-level signal
  -> Mastery band / Weakness
  -> Review Queue
  -> 新 Practice Attempt 验证
  -> confirmed Weakness 自动建立可管理 Memory
  -> 用户明确开启后才可发送给外部 Tutor provider
```

必须同时完成：

- Postgres 权威 schema、migration、ORM、确定性投影与删除图；
- 新 Exercise artifact 的稳定 target 映射与旧数据 `lesson_overall` 迁移；
- Review Queue、自动 Memory、Workspace Tutor Memory policy API；
- 复用 practice queue 的全量重算 Job，不新增服务；
- Tutor 的受限 Memory 注入与脱敏 trace；
- 已接受的复习 focus page、Reader 摘要和 Memory 管理界面；
- 固定离线 eval、focused tests 和完整自动化复验。

实现交回只代表候选完成，不代表 Slice Gate 通过。

## 3. 严格范围

### 包含

- 仅从已成功评分且仍有效的 Practice Attempt/Feedback 派生学习事实。
- Lesson Version 内稳定 Learning Target；新版本使用新 target 身份。
- 四档可见 mastery：证据不足、需要复习、学习中、较稳固。
- provisional/confirmed/resolved/dismissed Weakness。
- due/reviewing/awaiting_validation/snoozed/dismissed/resolved Review Item。
- confirmed Weakness 自动、确定性、幂等创建 `weakness` Memory。
- Memory 编辑、暂停、重新确认、归档和硬删除。
- Workspace 级 Tutor Memory 外发开关，默认关闭。
- 当前 Workspace/Course/Lesson 精确关系下最多 5 条、约 600 input token 的 Tutor Memory。

### 明确不做

- 不把阅读时长、滚动、查看反馈、未答题、Tutor history 或 Review Action 变成 mastery signal。
- 不用 LLM 计算 mastery、排序 Review、生成 Memory 文本、判断冲突或回填旧 target。
- 不新增 provider call、learning worker 服务、Qdrant Memory collection、Neo4j 或本地 JSON 权威。
- 不实现偏好 Memory、“已掌握”Memory、跨 Lesson Version 合并或跨账号画像。
- 不进入 Slice 3 Skill、Slice 4 MCP、认证、多租户 membership 或产品内自主多 Agent。
- 不顺手重做 Reader/Tutor/Practice 导航或视觉系统。

## 4. 执行规则

按 Batch A -> B -> C -> D -> E 顺序实施。每批完成后运行 focused checks，并记录文件、行为、检查结果和剩余风险。

- 保持 `apps -> academic_companion -> hello_agents` 依赖方向。
- Postgres 是业务事实；Redis/RQ 只投递；Qdrant 仍只保存可重建课程检索索引。
- 不读取、输出或提交 key、`.env`、连接串、内部地址、上传原文、敏感 prompt、日志、绝对路径或 provider 配置。
- 不运行真实 provider、真实 OCR、破坏性 Git 命令、commit 或 push。
- 只使用 fake provider 和公开/脱敏 fixture 验证。
- 若代码事实与已接受 Spec/ADR 冲突，停止对应部分并报告，不自行改变合同。
- 不把 prototype `UserModel`、`LearningAgent` 或 `hello_agents.memory` schema 直接搬入产品。

## 5. Batch A：Target 合同、migration 与 ORM

### 5.1 扩展练习 artifact

在不破坏已有 Practice Set 可读性的前提下：

- 新 Lesson Version 从 `learning_objectives` 建立稳定 `objective_1..N` target。
- 保留 `lesson_overall` 合成 target。
- 新 Practice Item 声明一个或多个 `target_key`；简答 rubric criterion 可声明 target key。
- artifact validator 必须拒绝未知 target、跨 Lesson Version target 和空映射。
- 旧 Practice Item 不调用 LLM 猜测，migration/backfill 统一映射到所属 Lesson Version 的 `lesson_overall`。

若 Slice 1 artifact 的兼容读取需要 schema version，采用最小向后兼容方式并增加测试，不原地篡改已生成 Set 内容。

### 5.2 Migration 与 ORM

先确认当前 migration head；预计从 Slice 1 的 `0016` 后新增顺序 migration，不硬编码错误 revision。实现 ADR 003/004 的权威表：

| 表 | 核心约束 |
|---|---|
| `learning_targets` | Workspace/Course/Course Version/Lesson/Lesson Version、target key；版本内唯一 |
| `practice_item_targets` | Item/Target/可选 criterion key；归属链一致、组合唯一 |
| `learning_events` | `practice_result`、Attempt/Feedback 唯一、时间 |
| `mastery_signals` | Event/Target 唯一、value/weight/outcome/AI 标记 |
| `mastery_states` | Target 唯一、band、内部 score、证据计数、策略版本 |
| `weaknesses` | Target 唯一、状态、首末负向 event、Memory suppression 水位、revision |
| `review_items` | Weakness 唯一、状态、due/reopen/reason snapshot |
| `review_actions` | append-only action 与 snooze 时间 |
| `learning_projection_jobs` | Workspace、幂等/request hash、状态、lease/retry/error/时间 |
| `learning_memories` | Workspace/Course/Lesson/Target/Weakness、kind/status/text/revision/时间；同 target 最多一个未归档 |
| `learning_memory_sources` | Memory/Event 组合唯一，只保存关系 |
| `learning_memory_revisions` | append-only 安全动作与前后 hash，不保存正文副本 |
| `learning_memory_policies` | Workspace 唯一、Tutor use 默认 false、policy revision |

所有表直接或可验证地受 Workspace 隔离；新增 FK、unique、check constraint 和索引。不要把通用 JSON bag 当领域模型。

### Batch A 验证

至少覆盖 migration、target mapping、旧数据 backfill、FK/unique/check、Workspace 归属和 ORM 删除顺序：

```powershell
python -m pytest -q apps/api/tests -k "learning or mastery or review or memory or migration"
git diff --check
```

在临时 Postgres 验证 `upgrade head -> downgrade -1 -> upgrade head`，不得触碰用户现有 volume。

## 6. Batch B：确定性投影、Review、Memory 与 API

### 6.1 信号与掌握度

严格实现 ADR 003：

- 单选 correct/incorrect：value `1.0/0.0`、weight `1.0`、非 AI。
- 简答 criterion full/partial/none：value `1.0/0.5/0.0`、聚合后 weight `0.6`、AI 标记。
- 同一 Attempt 对同一 target 最多一个聚合 signal。
- `ungradable`、失败、取消、未答题、无 Feedback 不产生 signal。
- 最近 10 个有效 signal，使用 Beta(1,1) 先验公式和已接受阈值。
- 内部 projection score 不通过公开 API 伪装成精确用户能力百分比。
- projection policy/version 显式保存；阈值变化只能经新合同和全量重算。

Feedback 正式提交时，同一事务创建 event/signal、重算 state/weakness/review，并在 Weakness 首次转 `confirmed` 时自动创建 Memory。重复 Feedback、worker delivery 或 recompute 必须成为 no-op，不得生成重复事件或 Memory。

### 6.2 Weakness 与 Review

- 第一个 value `<0.5` signal：`provisional` + 低承诺 due Review Item，mastery 仍可为证据不足。
- 至少两个不同 Practice Item 的负向 signal 且 band=`needs_review`：`confirmed`。
- 至少两个不同 Item 的后续 value `>=0.8` 且 band=`secure`：`resolved`。
- reviewed 只进入 `awaiting_validation`，默认三天后提醒，不增加 mastery。
- snooze 只接受 1/3/7/30 天；dismiss 不删除证据，新负向 event 可重开并增加计数。
- 推荐理由只保存 target、安全 event 类型、计数和时间，不复制答案、feedback 或 evidence 正文。

### 6.3 自动 Memory

- confirmed Weakness 自动创建，不显示逐条创建确认，不提供手动 promotion endpoint。
- 默认文本由确定性模板生成；不调用 provider。
- 自动 Memory 默认用于平台内部 Review 与学习状态。
- 用户可 PATCH `display_text`、pause、reconfirm、archive；DELETE 硬删除。
- 用户删除 Memory 后，不反向删除 Practice/Mastery；在 Weakness 保存不含正文的 suppression 水位，只有删除后的新独立负向证据再次满足确认条件才能重新创建，不能由旧事件重放或全量重算立即复活。
- resolved、相反证据、Lesson 新版本、source degraded 或 90 天无支持证据使 Memory 转 `needs_review`，停止 Tutor 使用；不静默宣称“已掌握”。
- 删除最后 source 后硬删除 Memory；revision 也不可回读已删除文本。

### 6.4 API

以现有 `/api/v1/workspaces/{workspace_id}` 风格实现 Spec 002 候选 API，保持稳定错误语义：

```text
GET  /learning-state
GET  /learning-targets/{target_id}
GET  /review-items
POST /review-items/{review_item_id}/actions
POST /learning-state/recompute
GET  /learning-jobs/{job_id}
GET  /learning-memories
PATCH/DELETE /learning-memories/{memory_id}
GET/PATCH /learning-memory-policy
```

要求：

- 所有查询先约束 Workspace；跨 Workspace 猜测 ID 返回 404。
- filter 支持 Course/Lesson/status，参数有数量和长度上限。
- API 只返回 band、证据计数、AI/确定性构成、时间和安全定位。
- 永不返回历史答案、正确答案、rubric、feedback 正文、prompt、evidence、provider/model、内部 hash 或 projection score。
- Memory policy 默认 false；PATCH 开启时用通俗文案明确说明摘要可能发送给配置的外部 AI，不做逐 Turn 弹窗。

### 6.5 重算 Job

- 单 target 更新同步、事务内完成。
- Workspace 全量重算创建 Postgres Job，复用 `practice` queue 和 worker/reconciler 模式；不新增 Compose 服务。
- 使用 Idempotency-Key + canonical request hash、claim/lease/heartbeat/retry/cancel 和最终权威重检。
- 重算只读 Postgres 有效事实，不调用 provider；input/output token 必须为 `null`。
- 晚到结果必须重检 Workspace、owner、lease、policy revision，删除后不得复活派生事实。

### 6.6 删除图

- Attempt 删除：移除 event/signal，锁定并重算 target；无来源派生事实与 Memory 清理。
- Set 删除：对其 Attempt 执行相同投影清理。
- Course 删除：硬删除 targets/events/signals/states/weakness/review/memory/job 相关事实。
- Workspace 删除：把全部 Slice 2 表、active job 取消和 reconciler 纳入现有权威删除图。
- source degraded：历史状态可读并标记变化，不产生新 signal；关联 Memory `needs_review` 且不进入 Tutor。
- 破坏性人工删除 smoke 仍留到 Stage 4 最终 Gate，但必须新增真实 Postgres 自动化测试。

### Batch B 验证

新增 focused domain/API/worker/deletion tests，至少运行：

```powershell
python -m pytest -q apps/api/tests -k "learning or mastery or weakness or review or memory"
python -m pytest -q apps/api/tests -k "delete or reconciler or practice"
python -m pytest -q apps/api/tests
git diff --check
```

测试必须包括信号矩阵、单次抗污染、两题确认、自动 Memory 幂等、删除后不复活、source degraded、重算重复投递、租约/取消、API 负面键和 Workspace 隔离。

## 7. Batch C：Tutor Memory 与已接受前端

### 7.1 Tutor 注入

- Policy 关闭时不得读取或发送 Memory。
- 只选择当前 Workspace/Course/Lesson 精确关联的 `active` Memory。
- 最多 5 条、约 600 input token；超限使用稳定排序与确定性截断，不做向量检索。
- 仅发送 target title 与用户可编辑说明；不发送 source event、答案、rubric、feedback 或证据正文。
- Tutor Turn trace 只记录使用数量和 Memory ID hash，不记录文本。
- Tutor UI 显示“本次将使用 N 条学习记忆”；可跳转管理或关闭 Workspace policy。
- 原有 Tutor 外部处理说明更新为：开启后，学习 Memory 摘要可能随问题发送给配置的外部 AI。

### 7.2 Review focus page

忠实实现 `SLICE_2_FRONTEND_CONCEPT.md`：

- Workspace 只增加紧凑“今日复习 N 项”入口，不做大卡片或 landing page。
- 完整流程进入接近整页的 focus page，并能返回且保留 Reader 状态。
- 桌面三栏：左侧密集队列/筛选，中间当前复习项，右侧推荐依据与 Memory 状态。
- 顶部 `复习队列 | 学习记忆` tabs。
- confirmed Weakness 自动显示为 Memory；不出现“记住这个薄弱点”创建按钮。
- provisional 明确写“初步建议”，不使用“你没有掌握”等确定结论。
- Reader 右栏只显示当前 Lesson 的 due/awaiting-validation 摘要并跳转 focus page。
- 用户可编辑、暂停、重新确认、归档、硬删除 Memory；删除 dialog 说明不删除 Practice 历史，未来新证据可能重新建立。
- Tutor policy 关闭时列表仍可管理，明确“不会发送给外部 AI”。

### 7.3 状态与响应式

实现 loading、empty、provisional、confirmed、awaiting_validation、resolved、source_degraded、job running/failed 全状态。

- `>=1100px` 三栏。
- `720-1099px` 两栏，依据抽屉。
- `<720px` 单栏，无横向滚动。
- 长 target、理由、Memory 文本和按钮不得重叠或溢出。
- 使用现有图标、tabs、toggle、menu 和 dialog；不嵌套卡片、不重做全局视觉系统。

### Batch C 验证

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
```

按项目现有测试方式补充 API 映射、scope reset、policy off、自动 Memory 展示和状态切换测试。不要只依赖人工 smoke。

## 8. Batch D：固定离线 eval

扩展 `apps/api/stage4_eval`，不要修改 Slice 1 已通过 case 的含义。最低矩阵：

- 单选/简答各类 signal value、weight 与 AI 标记。
- ungradable/failed/canceled/未答题无 signal。
- 一次错误仅 provisional；两个不同 Item 才 confirmed。
- confirmed 自动创建且仅创建一个 Memory。
- reviewed/snooze/dismiss 不提高 mastery。
- 两个独立正向验证、resolved 与 Memory `needs_review`。
- 旧 Item 只映射 `lesson_overall`。
- Feedback 重放、recompute、重复 delivery 幂等。
- Attempt/Set/Course/Workspace 删除后的可重算与不可回读。
- policy off 不向 Tutor 发送；policy on 仍满足 5 条/600 token 和 scope。
- API/eval report 不泄露答案、rubric、feedback、Memory 文本、prompt、路径或 provider 配置。

Hard gates 必须 100%；推荐理由可理解、排序有用和文案不过度断言作为 observational 指标，不用 LLM judge。

```powershell
python -m pytest -q apps/api/tests/test_stage4_eval.py
cd apps/api
python -m stage4_eval.runner --mode offline
cd ../..
```

## 9. Batch E：完整复验与交回

运行：

```powershell
python -m pytest -q
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
git status --short --branch
docker compose config
```

环境允许时，在不删除 volume 的前提下重建正式 Compose，验证 migration head、`/ready`、Web HTTP 200、practice worker 与重算 Job。无法运行必须写明具体原因，不能视为通过。

### 只交给用户执行的 Chrome smoke

1. 连续完成两个不同题目的负向作答，确认第一次仅“初步建议”，第二次满足条件后自动出现 Memory。
2. 查看四档 mastery、证据数量、AI/确定性标记和推荐理由，不应显示内部百分比。
3. 标记已复习、稍后、不适用，确认 mastery 不因操作上涨。
4. 开始新练习验证，确认新 Attempt 才改变状态。
5. 编辑、暂停、重新确认、归档和删除 Memory；确认没有逐条“创建 Memory”负担。
6. Tutor policy 关闭时确认不发送；开启一次后确认 UI 显示本次使用数量。
7. 切换 Workspace/Course/Lesson、刷新、返回 Reader，确认 scope 与状态不串线。
8. 检查窄视口、长 target/说明、三栏与抽屉，不重叠或横向溢出。
9. 浏览器 Network 不得出现答案、rubric、feedback 正文、Memory source、prompt、内部 score 或 provider 配置。

破坏性 Attempt/Set/Course/Workspace 删除人工 smoke 按用户决定继续保留到 Stage 4 最终 Gate。

## 10. 完成交回格式

向 Codex/用户报告：

- Batch A-E 每批实际修改文件和关键行为。
- migration revision、表/约束、API、queue/worker、Tutor 和 Web 组件清单。
- 自动 Memory 的创建阈值、幂等、防复活和外发 policy 实现位置。
- 每条验证命令的 pass/fail、测试计数和关键输出。
- 未运行检查及其具体环境原因。
- 当前 `git status --short` 完整清单。
- 与 Spec/ADR/前端概念不一致或需要产品选择的问题。
- 需要 Codex 独立复核的高风险点：投影公式、事务幂等、自动 Memory、删除图、重算 lease、Tutor 外发边界、安全投影和前端状态保留。

停在这里。不要运行真实 provider、OCR，不要修改 Gate 结论，不要 commit/push 或宣布 Slice 2 完成。后续由 Codex 独立 review、分块 OCR、完整复验并组织人工 Gate。

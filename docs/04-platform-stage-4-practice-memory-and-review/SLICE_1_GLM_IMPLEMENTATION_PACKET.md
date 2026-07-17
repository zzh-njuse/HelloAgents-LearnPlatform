# Stage 4 Slice 1 GLM 实现任务包

状态：可执行；Spec 001、ADR 001/002 与前端概念已于 2026-07-16 通过人工 Gate

用途：交给配置 GLM 的 Claude Code 或同类 coding agent 顺序实现。GLM 负责正式编码、测试和实现报告；Codex 保留需求解释、跨模块合同复核、OCR、完整复验、人工 smoke 协调、阶段总结和提交决策。

## 1. 开始前必须读取

按顺序完整读取，不得只依赖本任务包：

1. 根 `AGENTS.md`。
2. `docs/README.md`。
3. `docs/LEARNING_AGENT_BLUEPRINT.md`。
4. `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`。
5. `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`。
6. `docs/AGENT_COLLABORATION_PLAYBOOK.md`。
7. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`。
8. `docs/03-platform-stage-3-chapter-learning-and-tutor/STAGE_3_SUMMARY.md`。
9. 本目录的 `README.md`、`STAGE_4_INPUTS.md`、`STAGE_4_SLICE_PLAN.md`、`SLICE_1_PRACTICE_FACT_INVENTORY.md` 和 `SLICE_1_FRONTEND_CONCEPT.md`。
10. 已接受的 `specs/001-lesson-practice-attempts-and-trustworthy-feedback.md`。
11. 已接受的 `adr/001-practice-snapshots-attempts-and-deletion-authority.md`。
12. 已接受的 `adr/002-controlled-practice-generation-grading-queue-and-trace.md`。
13. `apps/api`、`apps/web`、`academic_companion` 中相邻实现与测试；以代码事实确定文件落点，不从任务包猜测现状。

开始时运行并记录：

```powershell
git status --short --branch
git diff --stat
```

当前未提交的 Stage 4 Spec、ADR、事实盘点、前端概念、索引、协作手册与本任务包是已知文档成果。保留所有已有 dirty files，不得回滚、覆盖、stash 或清理。

## 2. 总目标

在当前 Reader 内完成第一条可信练习闭环：

```text
当前发布课节 -> 生成独立 Practice Set -> 单选/简答作答
  -> 确定性或受控 AI 评分 -> 带引用反馈 -> 重做/历史/删除
```

必须同时完成：

- Postgres 权威 schema、migration、ORM 和安全投影；
- 独立 `practice` queue、worker、Job、lease、取消、重试和 reconciler；
- 受控 Exercise Author、无检索 Answer Grader、确定性单选评分；
- Practice API、删除权威、AgentRun 安全 trace；
- 已接受的三栏前端交互；
- 固定离线 eval、focused tests 和完整自动化复验。

实现交回只代表候选完成，不代表 Slice Gate 通过。

## 3. 严格范围

### 包含

- 当前激活 Course Version 的当前已发布 Lesson Version。
- `single_choice` 与 `short_answer`。
- 每组 1-10 题，默认 5 题；2 题及以上必须同时包含两种题型。
- 多个独立、不可变 Practice Set；重新生成不覆盖旧 Set。
- 不可变 Attempt；重新作答创建新 Attempt。
- 中文、英文与沿用课节语言。
- 单选同步确定性评分；简答异步 rubric 评分。
- 单次 Attempt 删除、整个 Practice Set 删除，以及 Course/Workspace 上游删除。

### 明确不做

- course-wide、跨课节或跨课程练习。
- 多选、判断、填空、代码执行、数学工具、文件答案或外部判题。
- Learning Event、Mastery、Weakness、Review Queue、长期 Memory。
- Skill、MCP、网页搜索、产品内自主多 Agent。
- 认证、多租户 membership、计费或金额成本。
- 人工教师批改、排行、证书、导出或 raw debug API。

不得顺手实现后续 Slice，也不得用 prototype、fixture 或框架示例重写已接受合同。

## 4. 执行规则

按 Batch A -> B -> C -> D -> E 顺序实施。每批完成后运行该批 focused checks，并记录改动文件、行为、检查结果和剩余问题。不要把功能、无关重构、格式化和文档清理混在同一大 diff 中。

- 保持 `apps -> academic_companion -> hello_agents` 依赖方向。
- Postgres 是业务事实；Redis/RQ 只投递；Qdrant 只用于可重建课程证据检索。
- 不读取、输出或提交 key、`.env`、连接串、内部地址、上传原文、敏感 prompt、日志、绝对路径或 provider 配置。
- 不运行真实 provider、真实 OCR、破坏性 Git 命令、commit 或 push。
- 只使用 fake provider 和公开/脱敏 fixture 做自动化验证。
- 若代码事实与 Spec/ADR 冲突，停止对应部分并报告，不自行改变产品合同。

## 5. Batch A：领域 artifact、migration 与 ORM

### 5.1 领域层

在 `academic_companion` 中新增小而纯的练习 artifact、严格 Pydantic schema、prompt builder 和 validator。它们可以表达 Exercise Author 与 Answer Grader 的结构化输入输出，但不得拥有数据库、HTTP、Workspace、队列或产品删除职责。

不要直接复用 `academic_companion/agents/assessor.py` 的 fallback question、固定 50 分或本地 memory 行为。

必须校验：

- 题型、数量、稳定 option key、唯一正确选项；
- answer spec、每个 option rationale、reference explanation；
- 简答 rubric 1-5 项且权重合计 100；
- citation key 只能引用当前 evidence ledger；
- verdict、整数分数和 `ungradable` 的一致性；
- 中英文输出语言；
- 所有字符串、列表、token 与数量预算。

### 5.2 Migration 与 ORM

当前 migration head 为 `0015_add_course_generation_output_language.py`；在确认代码事实后新增顺序 migration，预期为 `0016`。建立 ADR 001 的七类权威表：

| 表 | 必须表达的事实 |
|---|---|
| `practice_sets` | Workspace/Course/Course Version/Lesson/Lesson Version、不可变生成配置、语言、难度、题数、可见/删除生命周期、时间 |
| `practice_items` | Set、稳定 ordinal、题型、题干、选项 JSON、隐藏 answer spec、option rationale/reference explanation、rubric |
| `practice_item_citations` | Item、稳定 citation key、Document/Version/Chunk 与可读位置所需身份 |
| `practice_attempts` | Workspace、Item、递增 ordinal、严格 answer payload、状态、外部处理确认、提交时间 |
| `practice_feedback` | 唯一 Attempt、verdict、可选分数、rubric 结果、反馈块与已校验 citation key |
| `practice_jobs` | `generate_set|grade_attempt`、业务归属、请求摘要、幂等、预算、状态、lease、retry、usage、稳定错误码 |
| `practice_job_sources` | Generation Job 创建时固定的 Document Version 来源 |

关键约束：

- 所有表直接保留 `workspace_id`，查询必须先约束 Workspace。
- Set 归属链必须一致；Citation 必须属于固定 Course Version source snapshot。
- Set/Item/评分材料创建后不可原地修改。
- Attempt ordinal 在 Item 内唯一；同一 Attempt 最多一个 Feedback。
- 幂等唯一性至少覆盖 Workspace + Idempotency-Key，并以 canonical request hash 检测 payload 冲突。
- 隐藏评分材料留在服务端 JSON/结构化字段，普通 ORM 不得被直接序列化。
- 不新增空壳 `exercise_versions`、Concept、Mastery、Memory 或 Qdrant collection。

Practice Set 删除沿用 `deleting` 权威状态与 reconciler，不要仅为删除自行增加第八张业务表。若现有删除框架确实要求额外持久化删除 Job，先停止并向 Codex 报告合同与工程冲突。

### Batch A 验证

至少新增领域 validator 和 migration/ORM focused tests，并运行：

```powershell
python -m pytest -q apps/api/tests -k "practice or migration"
git diff --check
```

在可用的临时 Postgres 上验证全量 `upgrade head -> downgrade -1 -> upgrade head`，不得触碰用户现有 volume。

## 6. Batch B：Practice service、API、queue、worker 与删除

### 6.1 API 合同

严格实现 Spec 001 第 9 节的路径：

```text
POST/GET /api/v1/workspaces/{workspace_id}/courses/{course_id}/versions/{course_version_id}/lessons/{lesson_id}/versions/{lesson_version_id}/practice-sets
GET/DELETE /api/v1/workspaces/{workspace_id}/practice-sets/{set_id}
GET /api/v1/workspaces/{workspace_id}/practice-jobs/{job_id}
POST /api/v1/workspaces/{workspace_id}/practice-jobs/{job_id}/cancel
POST /api/v1/workspaces/{workspace_id}/practice-jobs/{job_id}/retry
POST/GET /api/v1/workspaces/{workspace_id}/practice-items/{item_id}/attempts
GET/DELETE /api/v1/workspaces/{workspace_id}/practice-attempts/{attempt_id}
```

创建 Set Job 与提交 Attempt 必须使用 `Idempotency-Key`。所有归属错误和跨 Workspace 猜测 ID 返回 404；版本不当前、未发布、来源降级或 payload 冲突使用现有 API 错误模式返回稳定 409/422。

普通 Item 读取只允许题型、题干、选项、难度、序号和用户可读 citation。提交前响应中必须完全不存在 correct option、answer spec、option rationale、reference answer、rubric、prompt、evidence 正文、provider/model 和内部 ID/hash 等禁止字段。

### 6.2 生成路径

- 创建 Generation Job 时验证当前 Course/Lesson Version、来源状态、1-10 题、语言、难度和显式 external-processing acknowledgement。
- 同事务固定 `practice_job_sources`，再 enqueue；enqueue 失败持久化 `queue_failed`。
- Exercise Author 只能使用 `PracticeEvidenceSearch` 和 `SubmitPracticeSet`；服务端覆盖 workspace/version/source filter。
- 最多 6 step、3 次 search、6 次 provider call、24K evidence token、12K output token、10 分钟 wall time；每次 search `top_k <= 5`。
- 完整 artifact 通过 schema、预算、citation 和来源快照校验后，才在单一最终事务创建 Set/Items/Citations 并可见。
- 不保存半成品，不产生 fallback 题目；取消、删除或晚到结果不得复活 Set。

### 6.3 作答与评分

- 单选只接受 option key；服务端确定性比较，单事务写入 Attempt 与 Feedback，不调用 provider、不创建 AgentRun。
- 单选 Feedback 显示用户选择、正确答案、所选错误项为何错误、正确项为何成立及资料位置；得分只能是 0 或 100。
- 简答最长 8,000 字符；创建 Attempt/Grading Job 前要求独立 external-processing acknowledgement。
- Answer Grader 只能读取该 Item 固定 answer spec、rubric、必要 evidence 和当前 Attempt；不得 search、web、MCP、memory 或调用其他工具。
- 最多 2 次 provider call、12K evidence/rubric token、3K output token、3 分钟 wall time。
- 正式 Feedback 必须一次性包含 verdict、适用时的 0-100 整数分、逐 rubric 结果、具体错误/遗漏、正确思路、简洁参考讲解、行动建议和资料位置。
- `ungradable` 不伪造数值分；provider/结构失败不创建 Feedback，绝不固定返回 50 分。
- retry 复用同一 Attempt 与 Job；不重复创建正式 Feedback。

### 6.4 Queue、状态与 reconciler

- 新增独立 `practice` RQ queue 和 `practice_workers.py`，不得复用 course/tutor queue。
- 沿用现有 Job 状态：`queued|running|retry_wait|queue_failed|cancel_requested|canceled|succeeded|failed`。
- Attempt 使用 Spec 001 定义的评分状态；状态映射必须有 focused tests。
- worker 领取 row lock，维护 worker id、attempt count、lease 和 heartbeat。
- 检索前、provider call 前后、最终事务前检查取消与 Workspace/Course/Set/Attempt 权威状态。
- 扩展 `services/jobs.py` reconciler，只恢复 stale/到期 Practice Job，不重新创建业务资源。
- 为 settings、Compose worker 命令和 readiness 采用现有小范围模式；不要新增服务类型以外的基础设施。

### 6.5 AgentRun 与安全 trace

- 为 AgentRun 增加 nullable Practice Job 关联，角色增加 `exercise_author` 与 `answer_grader`。
- Exercise Author 只记录白名单 tool name、ordinal、状态、result count、latency 和稳定错误码。
- Grader 可以是无 tool AgentRun；若使用结构化提交工具，只记录安全元数据。
- 安全运行摘要的 Course 过滤和身份投影必须识别 Practice Job，已删除对象只显示“已删除对象”。
- Run/ToolCall/日志不得保存题干、选项、用户答案、正确答案、answer spec、rubric、feedback、prompt、evidence 正文、原始响应或 provider 原始错误。

### 6.6 删除权威

- Attempt 删除先使其不可读，再取消评分并删除 Feedback、Grading Job trace、Job 和 answer payload；不影响其他 Attempt，ordinal 不重排。
- Set 删除先标记 `deleting`、隐藏并阻止新 Attempt，再按 Feedback -> Attempt -> Item Citation -> Item -> Job trace/Job -> Set 清理。
- Course 删除先清理全部 Practice 派生事实，再删除 Course/Lesson Version；不删除来源 Document。
- Workspace 删除把 Practice active jobs、计数、取消、清理顺序和 reconciler 全部纳入现有删除图。
- 来源删除不删除历史 Set；citation 显示不可用，`source_degraded` 时整个历史 Set 只读，禁止新生成、提交新 Attempt、重做或重新评分。
- 每个 worker 最终提交必须抵抗删除后的晚到结果。

### Batch B 验证

新增/更新 API、queue、worker、reconciler、AgentRun、Course 删除和 Workspace 删除测试。至少运行：

```powershell
python -m pytest -q apps/api/tests/test_practice_api.py
python -m pytest -q apps/api/tests -k "practice or agent_run or delete or reconciler"
python -m pytest -q apps/api/tests
git diff --check
```

测试必须包含 workspace 隔离、幂等冲突、答案泄露负面键集合、queue failure、retry、cancel、stale lease、重复投递、预算耗尽、未知 citation、来源降级、删除与晚到结果。

## 7. Batch C：已接受的 Reader 练习界面

### 信息架构不得改写

```text
左侧：课节目录
中间：[正文] [练习]，完整练习始终在这里
右侧：[Tutor] [练习记录]
```

基于现有 `CoursePanel.tsx`、`TutorPanel.tsx`、`api.ts` 和样式系统实现。可新增聚焦组件，例如 `PracticePanel.tsx` 与 `PracticeHistoryPanel.tsx`，但不要重做 Workspace 导航或视觉系统。

### 交互合同

- 中间正文/练习与右侧 Tutor/练习记录是两个独立切换状态。
- 打开 Tutor、切换右侧 tab 或暂时回正文时，保留当前 Set、题号、未提交答案、Feedback 展开状态、进度和合理滚动位置。
- 无 Set 时显示题数、难度、语言、外部处理说明和明确生成命令。
- 生成中就地显示任务身份：课程名、课节名、题数、状态，并提供适用的取消入口。
- 主区一次聚焦一道题，稳定显示题号、Set 身份、难度、语言和总进度。
- 单选与简答反馈完整显示 Spec 要求；citation 继续采用“文件名 > 章节路径 > 第 N-M 页”，无页码时不猜测。
- 右侧练习记录只负责 Set 切换、完成进度、Attempt 历史与状态，不复制完整题目。
- 支持重新生成新 Set、重新作答、删除 Attempt 和删除 Set；所有危险删除需沿用现有明确确认模式。
- 所有 external-processing acknowledgement 必须由用户显式确认，不预选，不合并生成与简答评分两次确认。
- loading、空、失败、queue_failed、grading、source_degraded、deleting 均按 `SLICE_1_FRONTEND_CONCEPT.md` 呈现。
- 有活动 Job 时轮询，终态停止；切换 Workspace/Lesson 时不得显示上一 scope 的数据。

### 视觉与响应式

- 保持现有安静、紧凑、可扫描的产品界面；不做 landing page、装饰性 hero 或嵌套卡片。
- 使用现有 lucide 图标、tabs/segmented control、checkbox/select/input 等合适控件。
- Chrome 桌面是人工基线；窄视口优先保留中间练习，目录和右栏变成可打开区域，不把题目压成窄列。
- 长题干、长选项、长反馈、中文/英文和引用不得重叠、溢出或阻断滚动。

若实际组件结构无法同时实现状态保留和独立右栏切换，停止该部分并报告，不得自行改成“在 Tutor 栏里做完整练习”。

### Batch C 验证

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
git diff --check
```

补充与现有 Web 测试方式一致的 API 映射、状态隔离和关键渲染测试；不要只依赖人工浏览。

## 8. Batch D：固定离线 eval

建立独立 Stage 4 离线 eval，建议结构：

```text
apps/api/stage4_eval/
  __init__.py
  cases.json
  metrics.py
  report.py
  runner.py
apps/api/tests/test_stage4_eval.py
```

可以复用 Stage 3 eval 的安全 runner/report 模式，但不得修改 Stage 3 已关闭结论或把普通全量 pytest 冒充固定 eval。

最低 case 矩阵：

- 生成：单题、混合题型、中文、英文、无证据、未知 citation、invalid rubric、预算耗尽、取消、提示注入不扩大 scope。
- 单选：正确/错误确定性评分、无 provider call、提交前无答案泄露。
- 简答：正确、部分正确、错误、ungradable、结构修复、评分失败、答案过长、无 retrieval、无固定 50 分。
- 运行：queue_failed/retry、幂等、重复投递、stale lease、晚到结果。
- 范围：Workspace/Course/Lesson Version/source snapshot 隔离。
- 删除：Attempt/Set/Course/Workspace 后不可回读答案或 Feedback。
- 隐私：答案、评分材料、prompt、evidence 不进入日志、trace 或 eval report。

Hard gates 必须 100% 通过：schema/citation、scope、答案隐藏、确定性评分、失败不提交半成品、取消/删除抵抗晚到结果和语言一致性。题目可回答性、歧义率、难度、干扰项、rubric 覆盖和反馈清晰度先作为 observational 指标，不自创普适阈值或调用 LLM judge。

默认命令建议：

```powershell
cd apps/api
python -m stage4_eval.runner --mode offline
```

报告沿用脱敏、机器可读和 Git 忽略边界，不包含题目、答案、反馈、fixture 正文、prompt、evidence、路径、provider 配置或测试 stdout/stderr 全文。本任务不实现或运行真实 provider eval。

### Batch D 验证

```powershell
python -m pytest -q apps/api/tests/test_stage4_eval.py
cd apps/api
python -m stage4_eval.runner --mode offline
cd ../..
git status --short
git diff --check
```

## 9. Batch E：完整复验与交回

### 自动检查

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

若环境允许，在不删除数据、不重建 volume 的前提下：

```powershell
docker compose build
docker compose up -d
docker compose ps
```

随后验证 migration head、API `/ready`、Web HTTP 200，并用 fake provider 完成一条 API 业务 smoke。无法运行的检查必须报告具体环境原因，不能写成通过。

### 只交给用户执行的 Chrome smoke

1. 在有可靠 citation 的已发布课节生成中文和英文 Practice Set。
2. 核对生成任务身份、取消/重试、多个 Set 切换和当前 Lesson 隔离。
3. 提交单选，核对选择、正确答案、两侧解释和资料位置。
4. 提交简答，核对独立外发确认、grading 状态、AI 标识、分数/verdict/rubric、具体讲解和引用。
5. 打开 Tutor、练习记录、正文后返回，确认草稿答案、题号、反馈和进度未丢失。
6. 重新作答，查看并删除单个 Attempt；删除整个 Set。
7. 核对来源降级、queue failure、长文本、窄视口和滚动状态。
8. 浏览器 Network 中不得出现隐藏评分材料、prompt、evidence、provider 配置或内部路径。
9. 回归 Reader、Tutor、课程生成、运行记录和 Workspace/Course 删除。

## 10. 完成交回格式

向 Codex/用户报告：

- Batch A-E 每批实际修改文件与关键行为。
- migration revision、表/约束、API 路由、queue/worker 和前端组件清单。
- 每条验证命令的 pass/fail、测试计数和关键输出。
- 未运行检查及其具体环境原因。
- 当前 `git status --short` 完整清单。
- 任何与 Spec/ADR/前端概念不一致、可能泄密、删除不完整或需要产品选择的问题。
- 需要 Codex 独立复核的高风险点：答案投影、幂等、晚到结果、删除图、AgentRun、状态保留和 eval 报告。

停在这里。不要运行真实 provider、OCR，不要修改 Stage 4 Gate 结论，不要提交、push 或宣布 Slice 1 已完成；后续由 Codex 独立 review、分块 OCR、复验并组织人工 Gate。

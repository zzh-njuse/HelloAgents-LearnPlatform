# Stage 4 Slice 3 GLM 修正任务包 001

状态：待 GLM 执行
日期：2026-07-18
依据：已接受的 Spec 003、ADR 005 和 `SLICE_3_GLM_IMPLEMENTATION_PACKET.md`

## 1. 背景与目标

GLM 5.2 已交回 Slice 3 第一版候选实现。Codex 独立复核确认原有 43 个 focused tests 通过，但测试未覆盖若干已接受合同；当前实现仍存在最终提交权威、学习状态校准、预算、usage 和公开投影缺口。

本任务只修正这些合同缺口，不改变已接受产品设计，不增加第二种 Skill、模式切换、MCP、多 Agent 或新的长期学习事实。不要用固定问题、关键词、fixture 或 smoke 答案硬编码行为。

## 2. 开始前必须读取

完整读取并遵循：

- 根 `AGENTS.md`
- `docs/README.md`
- 四份产品方向文档，尤其 `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- Stage 4 README、`SLICE_3_INPUTS.md`、`SLICE_3_FRONTEND_CONCEPT.md`
- `specs/003-evidence-guided-diagnostic-scaffold-skill.md`
- `adr/005-product-owned-versioned-teaching-skill-runtime.md`
- `SLICE_3_GLM_IMPLEMENTATION_PACKET.md`
- 本修正任务包
- 相邻 Tutor、Practice worker/authority、readiness、API schema、Web 和测试代码

先运行 `git status --short --branch`。现有 Slice 3 dirty diff 是已知候选实现；`.tmp/`、`artifacts/` 以及其他未知改动不得读取、清理、回滚或提交。

## 3. 已独立确认的问题

### 3.1 P0：所有成功路径必须经过最终权威检查

当前 Skill 正常路径只检查 Workspace、Session 和 Turn status，没有检查精确 `worker_id`、未过期 lease、heartbeat lost、Course/Lesson version 和最终引用来源。`无课程证据且无可用学习状态` 的 limitation 提前成功路径甚至完全绕过最终权威检查。

修正要求：

- production worker 将本次 claim 的 `worker_id` 和 lease-lost 信号显式传入 Tutor 执行入口；不要依赖函数返回后才检查 heartbeat。
- 在写入任何成功 answer/citation、将 Turn/AgentRun 标为 succeeded 之前，统一调用一个最终权威检查；正常回答、repair 后回答和确定性 limitation 都必须走同一检查。
- 检查至少包含：Workspace active；Session active；Turn 仍为 running；`turn.worker_id` 精确等于本次 owner；lease 存在且未过期；heartbeat 未报告 lost；Course active 且仍为 Session 固定的 active version；lesson scope 的 LessonVersion 仍 published/current；本次 ledger 中引用的 SourceDocument/DocumentVersion 仍 active/current/ready。
- owner 被替换、lease 过期、cancel requested、Session deleting、Workspace/Course 删除、LessonVersion 替换、来源删除/换版/降级时，晚到结果不得写入回答、citation 或 succeeded 状态。
- duplicate delivery 不得再次调用 provider 或新增 AgentRun/回答；`retry_wait` 未到 `next_attempt_at` 不得 claim，到期后才允许 claim。

优先复用 Practice 已验证的 `_check_active` / final-authority 模式，但不要制造 `apps -> academic_companion` 反向依赖。

### 3.2 P0：certainty 必须按被诊断目标校准

当前实现把所有目标支持的 certainty 合并成一个全局集合。只要任意目标存在 confirmed weakness，模型就可能把另一个仅 provisional 或无证据的目标标为 confirmed。

修正要求：

- 给 provider 使用的安全学习状态投影分配本次 Turn 内部、非数据库 ID 的目标引用，例如 `t1`、`t2`。
- `learning_diagnosis` 的内部结构必须指明它诊断的目标引用；服务端逐目标验证 certainty，只允许该目标真实支持的 `confirmed | provisional | resolved | insufficient`。
- completion 仍只能表示完成阅读，不能支持 mastery 或 confirmed weakness；无 weakness 证据的目标只能使用 insufficient。
- 内部目标引用不得进入公开 API、SSE、普通 trace 或持久化 answer 正文；持久化前剥离。用户应看到目标标题、诊断文本和 certainty，而不是内部 ID。
- 增加至少两个目标的正反例：A confirmed/B provisional，B 不得借 A 的证据输出 confirmed；不存在对应目标引用也必须拒绝并最多 repair 一次。

### 3.3 P0：provider token 未报告不能伪装为 0

当前 `(usage[...] or 0)` 会把缺失 usage 写成 0；repair 聚合也会掩盖任一调用缺失的维度。

修正要求：

- input/output 两个维度分别聚合；该维度任一 provider 调用缺失时，Turn 和 AgentRun 对应字段均为 `None`。
- 全部调用都报告时保存精确总和；内部 evidence/output 预算估算不得写成 provider usage。
- plan-only limitation、正常 answer、一次 repair 三条路径均应用相同规则。
- 测试覆盖完整、全缺、仅缺 input、仅缺 output、repair 某一调用缺失；Turn 与 AgentRun 必须一致。

### 3.4 P1：真正执行学习状态约 800-token 预算

当前只限制 5 条 Memory 和 10 条 Completion；Weakness/target 无上限，`total_chars` 计算后未使用，因此不能保证约 800 tokens。

修正要求：

- 使用仓库已有的稳定 token 估算方式；若该层没有 tokenizer，可使用明确记录并测试的保守字符预算，默认对应约 800 tokens。
- Memory、Completion、target title、mastery band、weakness certainty/status 全部计入预算。
- 选择顺序必须确定且可解释，优先保留与精确 lesson scope 匹配、active Memory、confirmed/provisional weakness 和较新的有效状态；不得因数据库无序导致结果漂移。
- 达到预算后截断完整条目，不截断成会改变含义的半条状态；trace 只记录实际选择的数量和安全 reason，不记录正文。

### 3.5 P1：公开的“实际使用”计数必须反映注入而非仅选择

Skill 路径只写 `TeachingContextSelect`，但 `turn_detail` 仍读取 `LearningMemoryContext` 和 `LessonCompletionContext`，因此 UI 会把实际使用恒显示为 0。

修正要求：

- `memory_count` / `completion_count` 表示最终 answer prompt 实际注入的条数。
- plan 为 `irrelevant`/`unavailable`、policy disabled 或无匹配状态时均为 0；`required`/`helpful` 且实际注入时才返回真实条数。
- 可复用现有两个安全计数 ToolCall，或统一改为可稳定查询的安全 trace；不得记录 Memory/Completion 正文。
- Web 保持当前简洁文案，但须能显示正确的最近一次实际使用计数。

### 3.6 P1：certainty 需要进入安全公开投影

领域 answer block 已有 `certainty`，但 API `TutorAnswerBlock`、SSE 和 Web 类型会将其丢弃。

修正要求：

- 仅为 `learning_diagnosis` 公开受限 certainty；其他 block 为 null/省略。
- API、SSE、Web 类型和渲染保持一致，不公开内部目标引用、hash、prompt 或隐藏分数。
- Web 以紧凑、可理解的中文标签展示，例如“已确认”“初步判断”“证据不足”“已改善”；不要显示原始枚举给普通用户。

### 3.7 P1：Skill 必须进入 `/ready` 检查

ADR 005 明确要求启动/ready 检查 allowlist Skill 存在、metadata 匹配且 hash 可计算。当前 `/ready` 未覆盖。

修正要求：

- 在 `services/readiness.py` 和 `/ready` 聚合中加入不泄露路径、prompt 或 hash 的 Skill 可用性检查。
- 正常返回安全的可用状态；Skill 缺失、metadata/hash 不可解析时 `/ready` 为 degraded，并只返回稳定非敏感 detail。
- capability endpoint 的 503 和 worker 的 `teaching_skill_unavailable` 语义保持不变。

### 3.8 P1：输入、幂等和数据库合同收紧

- `TutorTurnCreate` 对客户端伪造的 Skill/mode/path/hash 字段应稳定 422，而不是依赖 Pydantic 默认静默忽略；使用 `extra="forbid"` 并修正现有误导测试名称和断言。
- 幂等比较完整校验服务端解析的 Skill ID、version、hash，不能只比较 hash。
- ORM metadata 同步声明三字段 all-null/all-non-null check constraint，使 SQLite 单测建表与 Postgres migration 合同一致；migration 0019 保持单 head 和可回滚。
- 修正 plan fallback 与首个 search 共用 trace ordinal 的问题；同一 AgentRun 内 ToolCall ordinal 应稳定、单调且不重复。

### 3.9 P1：失败 AgentRun 保留真实进度

当前 Skill 运行中的 AgentRun 在 worker rollback 后丢失，worker 另建的失败 run 没有真实 step/token 进度。

修正要求：

- 每个受控 decision step 在 budget check 通过、provider/retrieve 调用前更新真实 step_count。
- 失败、取消和 lease lost 后保留该 attempt 的真实 step_count；不要以 ToolCall 数推断，也不要产生语义重复的零步失败 run。
- provider usage 只有已实际返回且完整报告的维度才能进入失败 run；不能估算。
- 测试至少覆盖 plan 首次 provider 失败、plan 成功后 search 失败、answer 无效且 repair 无效、owner/lease 最终检查拒绝。

## 4. 允许修改的范围

为完成上述修正，可修改：

- `academic_companion/teaching_skills/**`
- `apps/api/learn_platform_api/db/models.py`
- `apps/api/alembic/versions/0019_add_tutor_teaching_skill_snapshot.py`
- `apps/api/learn_platform_api/schemas/tutor.py`
- `apps/api/learn_platform_api/services/tutor.py`
- `apps/api/learn_platform_api/services/tutor_generation.py`
- `apps/api/learn_platform_api/services/readiness.py`
- `apps/api/learn_platform_api/routers/health.py`
- `apps/api/learn_platform_api/routers/tutor.py`
- `apps/api/learn_platform_api/tutor_workers.py`
- `apps/api/tests/test_tutor_skill.py`、相邻 Tutor/worker/readiness tests
- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/styles.css`
- 必要的 Slice 3 eval fixture/runner/report

不要修改 Slice 2 的投影公式、Memory/Weakness/Review 状态机或 Practice 产品行为。若发现这些既有合同本身阻塞修正，停止对应部分并报告，不得自行改写。

## 5. 必须新增的回归矩阵

至少覆盖：

1. final authority：正常回答和 plan-only limitation 各自参数化 owner replaced、lease expired、cancel requested、Session deleting、Course/Lesson version changed、source degraded；全部无回答/citation/succeeded。
2. worker：duplicate delivery no-op；retry_wait 未到期不 claim、到期只 claim 一次；heartbeat lost 不提交。
3. target calibration：多目标 certainty 正反例、未知 target ref、completion 不升级 mastery。
4. context budget：超量 weakness/target/长 Memory/长标题后仍在预算内，选择确定，scope 不泄露。
5. usage：plan-only、answer、repair 的四种缺失组合；Turn/AgentRun 一致。
6. actual-use counts：selected-but-irrelevant 为 0，required/helpful 为实际注入数，policy off 为 0。
7. public projection：certainty 可见；内部 target ref、Skill hash/path/prompt、projection score、答案、rubric、feedback/evidence 正文仍不可见。
8. create/idempotency：伪造额外字段 422；ID/version/hash 任一冲突为 `idempotency_key_conflict`。
9. readiness：Skill 正常 ready；缺失/篡改时 degraded 且无敏感 detail。
10. failed trace：真实 step_count、无重复 AgentRun、ToolCall ordinal 单调不重复。

不得用 mock 掩盖最终 `db.refresh()` 后的 SQL 状态。owner/lease/version/source 变更应在 provider 或 search hook 返回前写入数据库，使最终检查观察到真实变更。SQLite 无法表达的并发语义需补 Postgres 测试或明确使用现有临时 Postgres fixture。

## 6. 验证命令

修正后至少运行并报告真实结果：

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

若 Docker Desktop 已运行，再执行 migration、Compose `/ready`、Web HTTP 200 和脱敏业务 smoke；否则如实列为未运行。不要调用真实 provider 或真实 OCR。

## 7. 交回要求

交回报告必须逐项说明：

- 3.1-3.9 每项如何关闭；
- 新增/修改文件；
- final-authority、target calibration、usage、budget、actual-use count、readiness 和失败 trace 的精确测试结果；
- 全量 API/eval/Web/Compose 结果；
- 未运行项及真实原因；
- 仍需 Codex 复核的风险；
- 完整 `git status --short`。

完成后停止：不要 OCR、不要 commit、不要 push、不要宣布 Slice 3 完成。

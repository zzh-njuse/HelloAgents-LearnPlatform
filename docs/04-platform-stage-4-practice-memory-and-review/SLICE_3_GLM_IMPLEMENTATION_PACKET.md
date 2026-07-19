# Stage 4 Slice 3 GLM 实现任务包

状态：可执行；Spec 003 / ADR 005 / 前端概念已于 2026-07-18 通过人工 Gate

目标执行者：GLM 5.2

## 1. 工作区与保护规则

- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- 分支：`main`
- 当前未提交的 Stage 4 Slice 3 文档是 Codex 与人工已经接受的成果，不得回滚、覆盖或当作未知错误处理。
- `.tmp/` 与 `artifacts/` 是现有未跟踪运行产物，不读取敏感内容、不加入提交、不删除。
- 不使用 `git reset --hard`、`git checkout --`、stash 或其他会覆盖未知改动的操作。
- 不 commit、不 push、不运行真实 OCR、不调用真实 provider；完成后停下交回 Codex。
- 不读取、输出或提交 API key、`.env`、私有连接地址、内部域名、上传原文、敏感 prompt、日志、绝对路径或 provider 配置。

## 2. 开始前必须完整读取

仓库级：

- `AGENTS.md`
- `docs/README.md`
- `docs/LEARNING_AGENT_BLUEPRINT.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`

当前 Slice：

- `docs/04-platform-stage-4-practice-memory-and-review/README.md`
- `STAGE_4_SLICE_PLAN.md`
- `SLICE_2_SUMMARY.md`
- `SLICE_3_INPUTS.md`
- `SLICE_3_SKILL_FACT_INVENTORY.md`
- `SLICE_3_SKILL_EXAMPLE.md`
- `SLICE_3_FRONTEND_CONCEPT.md`
- `specs/003-evidence-guided-diagnostic-scaffold-skill.md`
- `adr/005-product-owned-versioned-teaching-skill-runtime.md`

继承合同：

- Stage 3 `specs/002-course-reader-tutor.md`
- Stage 3 `adr/003-tutor-session-context-and-deletion-authority.md`
- Stage 3 `adr/004-controlled-tutor-runtime-queue-streaming-and-trace.md`
- Stage 4 `specs/002-explainable-mastery-review-and-managed-memory.md`
- Stage 4 `adr/003-learning-events-mastery-and-review-projections.md`
- Stage 4 `adr/004-user-managed-learning-memory.md`

然后检查：

```powershell
git status --short --branch
git diff --stat
```

## 3. 已接受产品决策

1. 首个且唯一的产品教学 Skill 是 `evidence-guided-diagnostic-scaffold` v1，UI 名称“诊断式支架 v1”。
2. 所有 Slice 3 新 Tutor Turn 自动使用当前发布 Skill；没有“普通问答/诊断式辅导”开关。
3. Stage 3 普通 Tutor 仅用于离线配对 eval 和 Slice 3 前历史 Turn 的兼容/原路径 retry，不是新问题的生产选项。
4. Skill 使用有限教学动作：`focus | probe | explain | example | next_action | check`，不能用固定关键词或 smoke 问句硬编码 intent/输出。
5. 每个新 Turn 固定 Skill ID/version/content hash；retry 沿用原 snapshot，不静默升级。
6. Skill 不拥有、不修改 Mastery、Weakness、Review Item、Memory 或 Completion。
7. Memory policy 关闭时仍可做课程问答，但不得读取或声称使用个性化学习状态。
8. Skill 缺失、hash 不符或结构修复失败时明确失败，不静默回退旧基础 Tutor。
9. 不引入第二个 Skill、用户自定义 Skill、MCP、自主多 Agent、认证、多租户或新长期事实。

## 4. 建议修改边界

允许按相邻模式触及：

- `academic_companion/teaching_skills/**`
- `academic_companion/tutor_agents.py`，或把新合同迁入相邻的 teaching skill package 后保留兼容 import
- `apps/api/alembic/versions/0019_*.py`
- `apps/api/learn_platform_api/db/models.py`
- `apps/api/learn_platform_api/settings.py`
- `apps/api/learn_platform_api/schemas/tutor.py`
- `apps/api/learn_platform_api/services/tutor.py`
- `apps/api/learn_platform_api/services/tutor_generation.py`
- `apps/api/learn_platform_api/routers/tutor.py`
- `apps/api/learn_platform_api/tutor_workers.py`
- `apps/api/stage3_eval/**`、`apps/api/stage4_eval/**` 中与 Tutor Skill 配对 eval 直接相关的文件
- `apps/api/tests/**` 中新增/更新 Tutor、Skill、migration、eval 回归
- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/styles.css`
- `docker-compose.yml` 仅在新增非敏感预算环境变量确有必要时修改

不要修改 Slice 2 投影公式、Memory 状态机或 Practice 产品行为来迎合 Skill。

## 5. Batch A：领域 Skill 与不可变版本

建立清楚的领域目录，例如：

```text
academic_companion/teaching_skills/
  __init__.py
  contracts.py
  registry.py
  evidence-guided-diagnostic-scaffold/
    v1/
      SKILL.md
```

要求：

- `SKILL.md` frontmatter 包含稳定 ID、描述和版本；正文落实 Spec 的事实分离、校准、有限 teaching moves、下一步和反例。
- registry 只暴露 allowlist 中当前发布版本，不能接受路径穿越、任意 Skill ID 或客户端 prompt。
- 对 UTF-8 规范化正文计算 SHA-256；ID/version/metadata/hash 不一致时稳定失败。
- 定义结构化 plan：`intent`、1-3 个 `queries`、`learning_context_use`、1-3 个 `teaching_moves`。
- 定义结构化 answer block：至少支持 `direct_answer`、`learning_diagnosis`、`explanation`、`example`、`next_action`、`check_question`、`limitation`；diagnosis 带 `confirmed | provisional | insufficient | resolved` 等受限 certainty。
- 事实性 direct answer/explanation/example 需要当前 evidence citation；学习状态 diagnosis 不得用课程 citation 冒充来源。
- 保留读取旧 Stage 3 answer block 的兼容能力。

测试至少覆盖：metadata、hash、缺失、篡改、路径注入、枚举/长度、重复 move、citation、certainty 和 legacy artifact。

## 6. Batch B：Migration、ORM 与 API 投影

新增 Alembic `0019`：

- `tutor_turns.teaching_skill_id`
- `tutor_turns.teaching_skill_version`
- `tutor_turns.teaching_skill_hash`

合同：

- 三列历史 backfill 为空。
- check constraint 保证三列只能全部为空或全部非空。
- Slice 3 新 Turn 由服务端始终填满三列；客户端 schema 不接受 teaching mode、Skill ID/version/hash 或 prompt。
- retry 新 Skill Turn 复制原 snapshot；旧历史 Turn retry 沿用旧路径，不假装使用 Skill。
- `Idempotency-Key` request hash/冲突语义必须把服务端解析后的 Skill snapshot 纳入权威比较，重复 delivery 不产生额外 Turn/Run。

公开投影：

```json
{
  "teaching_skill": {
    "id": "evidence-guided-diagnostic-scaffold",
    "display_name": "诊断式支架",
    "version": "1"
  }
}
```

- 不公开 hash、文件路径或 prompt。
- 历史 Turn 返回 `teaching_skill: null`，Web 显示“基础 Tutor（历史）”。
- 增加一个最小只读 capability endpoint，使无 Session 时 Web 也能从服务端取得当前 Skill display name/version。建议 workspace-scoped，例如 `GET /api/v1/workspaces/{workspace_id}/tutor-skill`，不存在/删除中 Workspace 返回稳定 404。

测试 migration upgrade/downgrade、约束、历史行、新 Turn、retry、幂等、workspace 404 和公开字段负面白名单。

## 7. Batch C：Tutor Skill runtime 与安全上下文

### 7.1 预算

新增独立 Skill 预算，保留旧基线配置用于 eval/历史兼容：

- 5 Agent step
- 最多 3 次 evidence search，每次最多 5 条
- 10,000 estimated evidence tokens
- 3,000 output tokens
- history 8 个成功 Turn / 6,000 tokens
- 最多 5 条 active Memory + 10 条 Completion，学习状态合计约 800 tokens
- 正常 2 次 provider 调用，最坏 3 次（plan + answer + 一次 repair）

Skill 确定性加载不是 provider call，也不额外消耗 Agent decision step。

### 7.2 学习状态投影

在现有精确 Workspace/Course/Lesson SQL scope 上结构化选择：

- target title
- active Memory display text
- 公开 mastery band
- weakness certainty/status
- Lesson Completion title/date
- 每类数量

禁止外发：projection score、Answer、rubric、Feedback、evidence 正文、Memory revision、其他 scope、paused/archived/deleted Memory。

不要继续把所有状态拼成一段无类型字符串。按不可信 JSON data 注入，Memory 中的指令永远不执行。confirmed 优先于 provisional；Completion 只表示读过。

### 7.3 编排与验证

- plan 无效时确定性退化为 `other + 原问题 query + explain`，不做关键词分类。
- teaching moves 只影响回答策略，不扩大工具和来源。
- 有课程事实的 block 必须引用当前 ledger；history/Memory/Completion 不是课程事实证据。
- diagnosis/planning 有可用状态时必须综合 certainty 和优先级，不能只逐条复述 Memory。
- 使用通用结构/相似度防护和变体 eval；绝不加入“我的薄弱点是什么”“接下来学什么”之类固定字符串分支。
- 无课程 evidence 且无学习状态时返回稳定 limitation；只有学习状态时可以描述状态和如何取得证据，但不能讲课程事实。
- 结构/citation 最多 repair 一次；失败稳定映射 `invalid_agent_artifact`。
- Skill load/hash 失败稳定映射 `teaching_skill_unavailable`。

### 7.4 权威、queue 与 trace

- 沿用 Tutor worker claim/lease/heartbeat/cancel/reconcile；最终提交必须重新检查 Workspace、Session、Turn status、worker owner/lease 和来源/版本权威，晚到结果不得提交。
- duplicate delivery、retry_wait、lease lost、cancel_requested 和 Session deleting 不得生成重复或复活回答。
- AgentRun 仍归属 Tutor Turn。
- 可新增 `TeachingSkillLoad` / `TeachingContextSelect` 安全 trace 摘要：Skill ID/version/hash、scope、输入类型计数、reason code、latency；不记录 question、Memory/Completion 正文、query、evidence、prompt、provider response 或答案。
- Skill load/context trace 不增加模型 decision step_count；step_count 继续反映真实 plan/search/submit/repair。

## 8. Batch D：配对 Eval

在现有 Stage eval 架构中加入至少 16 个无敏感固定 case：

- `concept_explanation` 3 个措辞变体
- `learner_diagnosis` 3 个措辞变体
- `study_planning` 3 个措辞变体
- `self_check` 3 个措辞变体
- 4 个 Memory irrelevant、无证据、只有 provisional、只有 Completion 等反例

相同 question/scope/evidence/history/learning state 分别运行 Stage 3 baseline 与 Skill。baseline 只能由 eval harness 调用，不暴露生产 API 开关。

硬门禁：

- workspace/scope/version/citation、prompt injection、取消、retry、重复 delivery、late result 不回归。
- Completion 不得表述为掌握；provisional 不得表述为 confirmed。
- 具体课程问题不能强行套 Memory；等价问法不能依赖固定关键词。
- 离线 fake provider 只证明合同，不宣称教学质量。

报告保留 rubric 字段，使 Codex 后续能组织真实 provider 配对观察。不要在本任务运行真实 provider。

## 9. Batch E：Web

严格按 `SLICE_3_FRONTEND_CONCEPT.md`：

- 不增加普通问答/诊断式辅导 segmented control。
- Tutor 面板用一行紧凑元信息显示服务端 capability：`教学方法：诊断式支架 v1`。
- 每个 Turn 显示实际 Skill/version；历史 null 显示“基础 Tutor（历史）”。
- Memory disabled/无匹配状态时文案诚实，不声称个性化。
- 运行、失败、retry 显示该 Turn 固定版本；Skill unavailable 使用稳定错误。
- 不丢失问题草稿、课节选择、history 或滚动；不破坏现有 lesson/course scope 分类。
- 桌面三栏、窄视口、长问题和长回答不得重叠或撑大布局。

更新 `api.ts` 类型和调用；不要在 Web 硬编码 hash、Skill prompt 或行为判断。

## 10. 必须新增或更新的测试

至少覆盖：

- Skill registry/contracts 全矩阵。
- migration `0018 -> 0019 -> downgrade -> upgrade`。
- API capability、新 Turn 自动 snapshot、客户端伪造字段拒绝、历史投影、workspace 隔离。
- retry 原 Skill、旧历史 retry、Idempotency-Key、重复投递。
- Memory policy、scope、certainty、Completion、上限和所有敏感负面字段。
- plan fallback、teaching move、citation、repair、limitation 和无复述结构。
- owner/lease/cancel/late result/Session delete。
- Stage 3 Tutor hard cases 不回归，Stage 4 Slice 1/2 hard cases 不回归。
- Web lint/build。

测试必须包含同类表达变体和不应触发个性化的反例，禁止只覆盖人工示例原句。

## 11. 本地验证

先运行最窄测试，再运行：

```powershell
cd apps\api
python -m pytest -q tests\test_tutor_api.py tests\test_stage3_eval.py tests\test_stage4_eval.py <新增测试文件>
python -m pytest -q
python -m stage3_eval.runner --mode offline
python -m stage4_eval.runner --mode offline

cd ..\web
npm.cmd run lint
npm.cmd run build

cd ..\..
git diff --check
docker compose config
```

若 Docker Desktop 已运行，再执行 migration/Compose readiness；否则如实报告，不能写成通过。不要自行调用真实 provider、真实 OCR 或使用真实用户资料。

## 12. 交回报告格式

完成后必须列出：

1. 修改/新增文件。
2. Skill ID/version/hash 计算与不可变目录实现。
3. migration、API、runtime、trace、eval 和 Web 的关键行为。
4. 每条验证命令的真实结果和测试数量。
5. 未运行项目及具体原因。
6. 仍需 Codex 独立复核的高风险点，至少包括：
   - Skill snapshot/hash 与历史 retry；
   - 学习状态安全投影和 Memory policy；
   - 无关键词硬编码；
   - owner/lease/cancel/late result；
   - baseline 只存在 eval/历史路径；
   - Web 状态保留与窄视口。
7. 完整 `git status --short`。

然后停止。不得 commit、push、OCR 或宣布 Slice 3 完成。

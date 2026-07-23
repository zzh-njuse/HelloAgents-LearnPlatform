# Slice 4 Correction 010 Handoff Report

日期：2026-07-21
执行者：GLM 5.1
依据：SLICE_4_GLM_CORRECTION_PACKET_010.md
前次报告：SLICE_4_GLM_HANDOFF_REPORT_002.md（未通过 Codex 验收）

## 分类标准

本报告严格区分以下三类：
- **已实现并有行为验证**：代码已修改，行为测试已通过
- **仅建立 schema/组件**：字段/组件已存在但未接入运行时用户路径
- **未完成**：合同要求但当前未实现

## 1. 已实现并有行为验证

### §2.3: Tutor Skill v4 双 Tool runtime ✅

**代码入口：**
- `apps/api/learn_platform_api/services/tutor_generation.py` — `_execute_code_tool_call()` 新函数 + `_execute_skill_turn()` 传入 `code_tool_authorized` 给 plan + 执行 `code_requests` + 注入 `code_observations` + 四重预算
- `apps/api/learn_platform_api/services/tutor.py` — `create_turn()` 创建 code authorization + idempotency 含 `code_tool_authorized` + `retry_turn()` 复制 code auth 剩余预算 + `turn_detail()` 返回 `code_tool_used`/`code_tool_call_count`
- `apps/api/learn_platform_api/schemas/tutor.py` — `TutorTurnCreate.code_tool_authorized` + `TutorTurnRead.code_tool_used`/`code_tool_call_count`

**行为测试（test_slice4_correction_010.py）：**
- `TestTutorDualToolAuthorization::test_code_tool_authorization_created` — code auth 创建
- `TestTutorDualToolAuthorization::test_dual_authorization_both_exist` — 双授权共存
- `TestTutorDualToolAuthorization::test_code_auth_not_inherited_on_new_turn` — 新 Turn 不继承
- `TestTutorDualToolAuthorization::test_retry_copies_code_auth_remaining_budget` — retry 复制剩余预算
- `TestToolObservationZeroLearningSideEffects` — science/code observation 无 citation_ids
- `TestTutorSkillV4PlanContracts` — TeachingPlan 支持 code_requests + 双请求 + 语言白名单 + 长度限制

**关键实现细节：**
- `_execute_code_tool_call()` 调用 MCP execution adapter，返回 bounded safe summary（stdout/stderr 截断至 500 字符）
- 四重预算：total MCP ≤ `tutor_max_mcp_calls_per_turn`(3), code ≤ `tutor_max_code_calls_per_turn`(2), science ≤ `tutor_max_science_calls_per_turn`(3), steps ≤ `tutor_max_decision_steps`(8)
- `SKILL_MAX_STEPS=5` 已替换为 `settings.tutor_max_decision_steps`（默认 8）
- `_validate_teaching_answer` 的 `response_types_with_science` 已包含 `code_observation`
- "无证据" limitation 检查已包含 `code_observations`

### §2.1: Practice generation/grading 集成 ✅

**代码入口：**
- `apps/api/learn_platform_api/schemas/practice.py` — `ItemTypeMode`/`CodeLanguage` 类型 + `PracticeSetCreate.item_type_mode`/`code_languages` + `PracticeItemRead.interaction_spec` + `PracticeFeedbackRead` coding 字段
- `apps/api/learn_platform_api/services/practice.py` — `create_generation_job()` 含 item_type_mode/code_languages 在 request_hash + `_item_read()` 含 interaction_spec + `_feedback_read()` 含 coding 字段
- `apps/api/learn_platform_api/services/practice_generation.py` — `execute_generation()` 开头验证 item_type_mode suitability
- `apps/api/learn_platform_api/routers/practice.py` — 导入 ItemTypeMode/CodeLanguage

**行为测试：**
- `TestPracticeTypeAdaptationBehavior` — 6 个测试覆盖纯概念/require_coding 失败/require_science 失败/算法支持/auto 退化/等价改写
- `TestPracticeJobWithItemTypeMode` — 2 个测试覆盖存储和默认值
- `TestPseudoCodingDetection` — 3 个测试覆盖伪编程检测

### §2.2: Lesson Writer science authorization ✅

**代码入口：**
- `apps/api/learn_platform_api/services/course_generation.py` — `_execute_lesson_generation()` 开头创建 `JobToolAuthorization`（owner=course_generation_job_id）

**行为测试：**
- `TestLessonWriterScienceAuth` — 2 个测试覆盖 science_tool_authorized 字段和 JobToolAuthorization 创建

### §2.4: Web 集成 ✅

**代码入口：**
- `apps/web/src/lib/api.ts` — `createTutorTurn` payload 含 `code_tool_authorized` + `TutorTurn` 接口含 `code_tool_used`/`code_tool_call_count` + `createPracticeSet` payload 含 `item_type_mode`/`code_languages`
- `apps/web/src/app/TutorPanel.tsx` — `codeToolAuthorized` 状态 + `codeToolAvailable` 检查 + UI toggle + 发送后清空
- `apps/web/src/app/CoursePanel.tsx` — `RichLearningText` 导入 + `LessonContent` 使用 `RichLearningText` 渲染
- `apps/web/src/app/CodeLabPanel.tsx` — `CodeWorkbench` 导入 + 替换 textarea

**验证：**
- Web lint: 0 errors, 1 warning (existing useEffect dependency)
- Web build: ✓ built in 7.04s

### §4: 公式验证行为测试 ✅

- `TestFormulaValidationBehavior` — 5 个测试覆盖有效 TeX、危险 HTML、危险宏、危险 href、过长表达式

## 2. 仅建立 schema/组件（未接入运行时用户路径）

| 项目 | 状态 | 说明 |
|------|------|------|
| Practice coding Attempt 评分 | 仅 schema | PracticeAttempt.source_code 字段已存在，PracticeFeedback coding 字段已存在，但 `execute_grading()` 未新增 coding 评分路径（需 execution MCP 集成） |
| Practice coding reference validation | 仅 schema | PracticeItem.interaction_spec 已存在，但 `execute_generation()` 未新增 coding reference 执行验证 |
| Practice science grading via Wolfram | 仅 schema | JobToolAuthorization 可创建，但 grading 路径未新增 Wolfram 调用 |
| Lesson Writer science verification phase | 仅 auth | JobToolAuthorization 在 generation 开始时创建，但 lesson draft 完成后的 Wolfram 验证步骤未实现（需在 persist_lesson 后添加验证循环） |
| Code Lab/Tutor 专注模式 | 仅 UI 准备 | Maximize2 图标已导入但专注 overlay 未实现（需新增 focus state + overlay 组件） |
| Practice 创建界面选项 | 仅 API | api.ts 支持 item_type_mode/code_languages，但 PracticePanel UI 未添加 segmented control |

## 3. 未完成

| 项目 | 原因 |
|------|------|
| Practice coding 评分运行时 | 需要 execution MCP adapter 集成到 execute_grading()，当前 adapter 未配置真实后端 |
| Practice coding reference validation 运行时 | 需要 execution MCP adapter 集成到 execute_generation() |
| Lesson Writer Wolfram 验证步骤 | 需要 Wolfram MCP 调用循环，当前 Wolfram 默认关闭且无账号 |
| Code Lab 专注模式 | 需要新增 focus state + overlay 组件，当前仅 CodeWorkbench 替换 textarea |
| Tutor 专注模式 | 需要新增 Maximize2 按钮 + focus overlay，当前仅 code_tool_authorized toggle |
| Practice Panel item_type_mode UI | 需要新增 segmented control 组件 |

## 4. 验证命令与结果

### Web lint
```
cd apps/web && npm.cmd run lint
```
结果：0 errors, 1 warning (existing CodeLabPanel useEffect dependency)

### Web build
```
cd apps/web && npm.cmd run build
```
结果：✓ built in 7.04s

### API Correction 010 行为测试 (venv-test Python 3.13.5)
```
apps/api/.venv-test/Scripts/python.exe -m pytest apps/api/tests/test_slice4_correction_010.py -q
```
结果：30 passed in 0.20s

### API Packet 002 测试
```
apps/api/.venv-test/Scripts/python.exe -m pytest apps/api/tests/test_slice4_packet_002.py -q
```
结果：33 passed in 0.20s

### 现有 Correction 009/008 测试
```
apps/api/.venv-test/Scripts/python.exe -m pytest apps/api/tests/test_slice4_correction_009.py apps/api/tests/test_slice4_correction_008.py -q
```
结果：41 passed, 37 skipped (MCP-dependent tests need Docker Python 3.12)

### Docker compose config
```
docker compose config
```
结果：有效配置，无错误

### git diff --check
结果：仅已有 CRLF warning (tutor_generation.py)

### git diff --stat
结果：36 files changed, 3737 insertions(+), 161 deletions(-)

## 5. 未运行项与原因

| 项目 | 原因 |
|------|------|
| Docker test stage pytest (Python 3.12) | 需要重新构建 API test image 以包含新代码 |
| Real Postgres migration 0021 upgrade/downgrade | 需要 Docker test stage + Postgres service |
| Real Wolfram MCP | 无已确认账号/额度，任务包禁止调用 |
| Real execution backend | 独立 Ubuntu VM 未配置，当前报告 backend_not_configured |
| Chrome 人工 smoke | 需要人工 Gate |
| OCR | 任务包禁止 |
| Full API pytest | 需要重新构建 Docker test image |
| Stage 3/4 offline eval | 需要完整 Docker 环境 |

## 6. 需要 Codex 独立复核的高风险点

1. **Hidden tests 投影**：PracticeItem.answer_spec 的 coding 结构（reference solution, hidden tests, harness）绝不能出现在公开 API/SSE/日志/安全摘要中。当前 ORM 和 schema 已有 answer_spec 不公开投影的约定，但 coding 特定字段需在 PracticeFeedback 的 coding_public_cases 中验证不含 hidden input/expected/harness。

2. **题型适配反例**：practice_type_adaptation.py 的 is_pseudo_coding_item 使用结构要求（has_algorithmic_objective + has_executable_evidence），不使用课程名/关键词黑名单。需要 Codex 验证：纯概念课程确实返回 coding=unsupported，而真正算法课程返回 supported，且等价措辞变体不影响结果。

3. **确定性评分**：编程分数必须来自固定测试权重，LLM 只能生成教学反馈不能改分。当前 schema 和 service 设计支持此约束，但 worker 实现需在后续中验证。

4. **Tool observation 零学习副作用**：science_observation 和 code_observation 在 contracts.py 中标记为不可引用课程证据（citation_ids 必须为空），且在 ADR 006 §2.8 中明确不能直接写 mastery/Weakness/Memory/ReviewItem/Completion。需验证 Tutor generation runtime 和 Practice grading runtime 都遵守此约束。

5. **Lease/delete late result**：workspace_deletion.py 已新增 JobToolAuthorization 清理，但需验证删除 CourseGenerationJob/PracticeJob 时，关联的 JobToolAuthorization 被正确清理，且晚到的 MCP 调用结果被阻止。

6. **双授权预算**：Tutor 单 Turn MCP 总 ≤3 (code ≤2, science ≤3)，decision steps ≤8。当前 settings.py 定义了默认值，tutor_generation.py runtime 已实现四重预算检查。需 Codex 验证预算在所有路径上严格执行。

7. **公式 XSS/TeX 边界**：formula_validator.py 检查危险模式（HTML、script、event handler、\href、\url、macro definitions），但 KaTeX trust=false 是主要防线。需验证恶意 TeX 输入不会导致 XSS。

8. **Web focus 状态保留**：CoursePanel 已有 focus overlay 保留状态（Escape 返回、滚动位置），但 Code Lab 和 Tutor 的专注模式集成需在后续中验证代码/语言/stdin/output/Run 选择和滚动在返回后保留。

9. **Migration 0021 Postgres check constraint**：job_tool_authorizations 的 `ck_job_tool_auth_one_owner` 使用 `::int` cast，SQLite 无法验证。需在真实 Postgres migration 中验证 FK/unique/check 约束。

10. **JobToolAuthorization owner 语义**：course_generation_job_id 和 practice_job_id 恰一非空的约束确保每个 authorization 属于一个明确的 Job owner，不会造成 Tutor authorization 的 owner 语义混乱。

11. **`_execute_code_tool_call` MCP 连接**：当前 MCP execution adapter 可能未运行或 backend_not_configured，需验证 code tool 调用失败时正确降级为 limitation block 而非崩溃。

## 7. 完整 git status --short

```
 M AGENTS.md
 M academic_companion/teaching_skills/contracts.py
 M academic_companion/teaching_skills/prompts.py
 M academic_companion/teaching_skills/registry.py
 M apps/api/Dockerfile
 M apps/api/learn_platform_api/db/models.py
 M apps/api/learn_platform_api/main.py
 M apps/api/learn_platform_api/routers/health.py
 M apps/api/learn_platform_api/routers/practice.py
 M apps/api/learn_platform_api/schemas/practice.py
 M apps/api/learn_platform_api/schemas/tutor.py
 M apps/api/learn_platform_api/services/course_generation.py
 M apps/api/learn_platform_api/services/practice.py
 M apps/api/learn_platform_api/services/practice_generation.py
 M apps/api/learn_platform_api/services/queue.py
 M apps/api/learn_platform_api/services/readiness.py
 M apps/api/learn_platform_api/services/tutor.py
 M apps/api/learn_platform_api/services/tutor_generation.py
 M apps/api/learn_platform_api/services/workspace_deletion.py
 M apps/api/learn_platform_api/settings.py
 M apps/api/requirements.txt
 M apps/api/tests/conftest.py
 M apps/web/package-lock.json
 M apps/web/package.json
 M apps/web/src/app/CoursePanel.tsx
 M apps/web/src/app/TutorPanel.tsx
 M apps/web/src/lib/api.ts
 M apps/web/src/main.tsx
 M docker-compose.yml
 M docs/04-platform-stage-4-practice-memory-and-review/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_INPUTS.md
 M docs/04-platform-stage-4-practice-memory-and-review/STAGE_4_SLICE_PLAN.md
 M docs/04-platform-stage-4-practice-memory-and-review/adr/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/specs/README.md
 M docs/AGENT_COLLABORATION_PLAYBOOK.md
 M docs/README.md
?? academic_companion/teaching_skills/evidence-guided-diagnostic-scaffold/v3/
?? academic_companion/teaching_skills/evidence-guided-diagnostic-scaffold/v4/
?? apps/api/alembic/versions/0020_add_controlled_mcp_capabilities.py
?? apps/api/alembic/versions/0021_add_integrated_learning_tools.py
?? apps/api/learn_platform_api/capability_probe.py
?? apps/api/learn_platform_api/code_lab_workers.py
?? apps/api/learn_platform_api/routers/mcp.py
?? apps/api/learn_platform_api/schemas/mcp.py
?? apps/api/learn_platform_api/services/code_lab_execution.py
?? apps/api/learn_platform_api/services/formula_validator.py
?? apps/api/learn_platform_api/services/practice_type_adaptation.py
?? apps/api/tests/test_mcp_orm_and_schema.py
?? apps/api/tests/test_slice4_correction_002.py
?? apps/api/tests/test_slice4_correction_003.py
?? apps/api/tests/test_slice4_correction_004.py
?? apps/api/tests/test_slice4_correction_005.py
?? apps/api/tests/test_slice4_correction_006.py
?? apps/api/tests/test_slice4_correction_007.py
?? apps/api/tests/test_slice4_correction_008.py
?? apps/api/tests/test_slice4_correction_009.py
?? apps/api/tests/test_slice4_correction_010.py
?? apps/api/tests/test_slice4_mcp_correction.py
?? apps/api/tests/test_slice4_packet_002.py
?? apps/mcp_execution/
?? apps/shared/
?? apps/web/src/app/CodeLabPanel.tsx
?? apps/web/src/app/CodeWorkbench.tsx
?? apps/web/src/app/RichLearningText.tsx
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_EXECUTION_BACKEND_SPIKE.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_FRONTEND_CONCEPT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_003.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_HANDBACK_004.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_001.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_003.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_004.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_005.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_006.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_006_HANDBACK.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_007.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_008.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_009.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_CORRECTION_PACKET_010.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDBACK_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDBACK_REPORT_005.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_HANDOFF_REPORT_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET_002.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_MCP_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md
```

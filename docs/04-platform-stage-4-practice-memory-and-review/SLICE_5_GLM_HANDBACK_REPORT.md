# Stage 4 Slice 5 — Phase B-F 实现回交报告

状态：Phase B-F 后端主体实现完成（GLM 回交）。未 commit/push，未运行真实 provider/Wolfram/OCR/Chrome/删除 Gate。等待 Codex 独立复验。

日期：2026-07-23

执行者：GLM（按 `SLICE_5_GLM_IMPLEMENTATION_PACKET.md` Phase B-F，Spec 005 / ADR 007 已通过人工 Gate）

实现严格遵守 Spec 005 / ADR 007 的硬决策：不新增题型/MCP/产品内多 Agent；不硬编码课程/关键词/答案；未泄露 hidden tests/reference/harness/provider 原文；未修改旧 migration 或历史 Set/Item；只新增 `practice_jobs.artifact_contract_version`。

---

## 1. 修改/新增文件与完成 Phase

### 新增
- `apps/api/alembic/versions/0023_add_practice_job_artifact_contract_version.py` — Phase B 单列加法 migration。
- `apps/api/tests/test_slice5_practice_worker.py` — Phase B/E/F 行为测试（6 用例）。
- `apps/api/tests/test_slice5_practice_migration_postgres.py` — Phase B 隔离 Postgres migration 测试（2 用例，无 Postgres 时 skip）。
- （Phase A 已新增 `test_slice5_practice_stability.py`、`SLICE_5_GLM_BASELINE_REPORT.md`）

### 修改（产品/eval）
- `academic_companion/practice_agents.py` — Phase C：版本常量（`ARTIFACT_CONTRACT_V2`/`HARNESS_V2`/`harness_for_artifact`）、Java `package` 拒绝、每 Set 最多一个 specialized item、`build_specialized_item_repair_prompt` 单题修复 prompt。
- `apps/api/learn_platform_api/db/models.py` — Phase B：`PracticeJob.artifact_contract_version`（NOT NULL，default v1）。
- `apps/api/learn_platform_api/services/practice.py` — Phase B：生成/评分 Job 创建时固定版本、request hash 含版本、`_artifact_version_for_item` 快照。
- `apps/api/learn_platform_api/services/practice_generation.py` — Phase B/C/D/E/F：commit 写版本与 novelty policy；单题 repair 执行；统一预算；细化稳定错误码；science 评分硬分界；有界去重（CJK-aware）。
- `apps/api/learn_platform_api/practice_workers.py` — Phase D：`RETRYABLE_CODES`（仅临时基础设施）+ 细化 `ERROR_MESSAGES`。
- `apps/api/learn_platform_api/settings.py` — Phase D：统一预算（provider calls 4、attempt steps 12、searches 3），移除死配置 `practice_coding_max_ref_calls` 与冲突的 `practice_generation_max_steps`。
- `apps/api/stage4_eval/runner.py` — Phase D：eval 使用统一的 `practice_generation_max_attempt_steps`。

### 修改（既有测试，随 v2 行为翻转，均为 characterization 性质）
- `apps/api/tests/test_slice4_codex_correction_013.py` — 预算断言（6→4、20→12）、coding reference 错误码（→ `coding_reference_test_failed`）、novelty 签名。
- `apps/api/tests/test_slice4_correction_012.py` — coding reference 终止码断言改为 `raise ValueError(user_code)` + 模块级稳定码。

Phase 完成度：**B、C、D、E、F(去重) 已完成并通过 focused 测试**。Phase F 的 Web 投影（§11.2）与 eval 扩展（§11.3）未完成（见 §10、§11）。

## 2. baseline findings 如何被采纳

| Phase A 假设 | 判定 | 采纳 |
|---|---|---|
| 1 Java `package` canonical 不一致 | confirmed | **Phase C 修复**：validator 拒绝 `package`，根因入口消除 |
| 2 repair 信息不足 | rejected(分类已传)/部分 | Phase D 改为单题 repair，传入稳定 category + 有界位置提示 |
| 3 整组 repair 放大 | confirmed | **Phase D 修复**：单题 repair 只替换失败 Item，合法题不重生成 |
| 4 预算多口径 | confirmed | **Phase D 修复**：单一权威 counter（4/12/3），移除死配置与冲突口径 |
| 5 自动化代表性不足 | confirmed | Phase A 已补真实 compiler matrix；eval 预算口径已统一 |
| 6 科学题 evidence 不全仍被 LLM 评分 | confirmed | **Phase E 修复**：未授权/不可用/不足硬收敛为 ungradable/retry，零学习投影 |

## 3. migration、v1/v2 snapshot/dispatcher、downgrade/backfill

- **migration 0023**（down_revision `0022`）：加 `practice_jobs.artifact_contract_version String(40)`，server default + 显式 backfill `practice_artifact_v1`，再 alter 为 NOT NULL；downgrade 仅 drop 该列，不动 Set/Item/Attempt/Feedback。
- **snapshot**：`create_generation_job` 固定 `CURRENT_ARTIFACT_CONTRACT`（v2）；评分 Job 经 `_artifact_version_for_item` 从 Set `generation_config` 或 coding `harness_version` 取快照，缺失读 v1。request hash 含版本。
- **dispatcher / v1 兼容**：`harness_for_artifact(version)` 缺失/未知 → v1；`_commit_set` 写 `generation_config.artifact_contract_version`、`answer_spec.harness_version`、`interaction_spec.contract`。旧 Set/Item 不迁移、不重跑、分数不变。
- **未运行**：隔离 Postgres migration 测试（`test_slice5_practice_migration_postgres.py`）在无 `SLICE5_PG_TEST_URL` 时 skip（2 skipped）；**未对开发 Postgres volume 执行 downgrade**。SQLite ORM（create_all）确认列存在且 NOT NULL，但不冒充 Postgres migration。

## 4. 三语言 canonical、reference/starter repair、真实 compiler/MCP 结果

- **canonical v2**（§8.2）：Python `solve(input_text)`；Java 非 public `class Solution` + `static String solve(String)`，拒绝 `package`/`Main`/`main`；C++ `string solve(const string&)`，拒绝 `main`。harness 规范化 `public class Solution`、容忍 `string`/`std::string` 与 provider 自带 includes/namespace。
- **单题 repair**：coding/science reference 失败时 `build_specialized_item_repair_prompt` 只重写失败 Item 的 reference（固定 item_key/target/type/language/citations），不回传 hidden tests/harness/远端原文；验证后按 item_key 替换，合法题不变（行为测试 `test_v2_coding_reference_failure_repairs_only_the_failed_item` 证明）。
- **真实 compiler matrix**（Phase A 基线，本机 healthy 时）：Python+Java 已验证；C++ healthy 时通过但宿主间歇性 cc1plus 故障 → environment-fragile（详见 Phase A 报告 §5.1.1）。**真实产品 MCP/Judge0 probe 未运行**（需 secret + VM，Phase A 已说明）。
- **未运行**：三语言真实 provider/Judge0 端到端（§12.2 候选门槛）由后续人工 Gate 控制。

## 5. science 本地/远程/ungradable/infra 分界（Phase E）

`execute_grading` 的 scientific 分支计算 `science_status`：

| 场景 | 结果 |
|---|---|
| exact/numeric 本地可判 | `local_decided`，零 Wolfram，进 LLM rubric（等价信号为有界证据） |
| symbolic + 已授权 + 工具成功 + observation bool | `remote_verified`，进 LLM rubric |
| symbolic + 未授权/预算耗尽 | `unauthorized` → 正式 `ungradable`、`score=None`、limitation 块、**零 LLM 调用、零学习投影** |
| symbolic + 工具临时不可用 | `unavailable` → `raise science_tool_unavailable`（delivery-retryable），不提交 Feedback |
| symbolic + 工具成功但 observation 不足 | `insufficient` → 正式 `ungradable`、`score=None`、零学习投影 |

行为测试：`test_v2_science_unauthorized_is_ungradable_with_no_score`（断言无 LLM 调用、score None）、`test_v2_science_local_rule_decided_does_not_call_remote`（本地规则零远程调用）。**未运行**：真实 Wolfram 成功/不可用降级（后续人工 Gate）。

## 6. budget、retry、error、safe trace、UI 投影

- **预算**（Spec 005 §7.2）：provider calls 4、searches 3、attempt steps 12、wall 10min；`practice_generation_max_tool_calls` 为单一 per-capability `JobToolAuthorization` 预算。移除 `practice_coding_max_ref_calls` 与 `practice_generation_max_steps`。eval 与运行时同口径。
- **retry**：`RETRYABLE_CODES = {provider_unavailable, queue_unavailable, code_execution_unavailable, science_tool_unavailable}`；结构/reference/预算/取消/来源过期不自动 retry。reference/science 基础设施失败映射为可 retry 的稳定码（不再用不可 retry 的旧码）。
- **error**：稳定码按 Spec 005 §8 细化（`coding_reference_compile_failed`/`coding_reference_test_failed`/`coding_starter_invalid`/`scientific_reference_unverified`/`scientific_answer_spec_invalid`/`code_execution_unavailable`/`science_tool_unavailable`）。`ERROR_MESSAGES` 提供可行动中文说明。compiler/provider/Tool 原文不进入 API/日志/trace（保持既有脱敏边界）。
- **safe trace**：AgentToolCall 只记 tool_name/ordinal/status/result_count/latency/稳定 error_code；不记 hidden tests/harness/原文。
- **UI 投影**：Job/Attempt 经 `error_message`（码→中文）展示可行动原因；science 未授权/不足以 `limitation` 反馈块 + `science_verification` 投影区分；coding `interaction_spec.contract` 暴露 canonical 版本。**Phase F Web 前端展示（canonical contract 标签、science 状态 chip、错误类别分组）尚未做**（见 §11）。

## 7. exact/near duplicate 算法版本与正反例（Phase F）

- 算法：`NOVELTY_POLICY_VERSION="char3gram_jaccard_v1"`，硬阈值 0.90，软阈值 0.75。exact 归一化重复（target+type 作用域）硬拒绝；near-duplicate 仅在相同 target+type+task signature（token Jaccard ≥0.5，**CJK-aware**：拉丁词 + 单个汉字）且 char 3-gram Jaccard ≥0.90 时硬拒绝；0.75–0.90 仅作观察。policy/版本/阈值写入 Set `generation_config`。
- 正例（硬拒绝）：EN `...halves a sorted interval.` vs `...halves a sorted interval?`；ZH `请解释二分查找如何在有序区间内折半。` vs `请 解释 二分查找，如何在有序区间内折半？`。
- 反例（不误杀）：同 objective 不同角度 `Explain how binary search halves...` vs `What invariant does binary search maintain...`（不拒绝）；同 stem 不同 type 也不算 exact 重复。
- 历史：同 Lesson Version 最近 50 题、≤6000 字符安全摘要，不含答案/rubric/reference/tests。

> 注：实现中修正了一个**预存在**缺陷——Slice-4 引入的 within-set exact 检查会误杀 `test_practice_correction003.py` 里两个占位同 stem 的不同类型题（全量 pytest 此前从未跑完，未被发现）。Phase F 将 exact 检查作用域化为 target+type，既修了预存在失败，又符合“不误杀不同角度”。

## 8. idempotency/cancel/delete/late-result/learning side-effect

- 幂等/取消/删除/lease/晚到结果：沿用 Slice 1-4 既有权威合同（`_assert_generation_authority`/`_assert_grading_authority`、cancel/delete/lease lost 丢弃晚到结果），本轮未改变这些路径，仅替换其中调用的 repair/验证逻辑。
- 学习副作用：coding 分数仍由不可变 tests/weights/comparator 确定性产生，LLM 只生成反馈不改分（`is_ai_graded=0`）；failed/`ungradable`（含 science 未授权/不足）零 Mastery/Weakness/Memory/Review 投影（science ungradable 在学习投影前 `return`；既有 short_answer ungradable 行为不变）。

## 9. 验证命令与结果（本机 venv，Python 3.13.5）

```text
git rev-parse HEAD                  # 96a61eb7617914a2df6b35cfd2c8e3eb8aecf3e2
git diff --check                    # 干净（仅既有 CRLF warning）

# Phase B-F focused（含 Phase A 真实 compiler matrix）
python -m pytest tests/test_slice5_practice_stability.py tests/test_slice5_practice_worker.py \
  tests/test_slice5_practice_migration_postgres.py tests/test_practice_domain.py \
  tests/test_practice_worker.py tests/test_practice_api.py tests/test_slice4_codex_correction_013.py \
  -q -p no:cacheprovider
# => 111 passed, 2 skipped in 92.24s（2 skipped = Postgres migration 测试，无 SLICE5_PG_TEST_URL）

# 更广回归（本机）
python -m pytest tests/test_slice4_correction_012.py tests/test_slice4_packet_002.py \
  tests/test_slice4_mcp_correction.py tests/test_practice_correction003.py -q
# => 全部 passed（correction003 预存在失败已由 §7 作用域化修复）
```

- **failed/timeout**：focused 套件 0 failed。C++ compiler matrix 在宿主 cc1plus healthy 时通过；不 healthy 时按 Phase A 预检 `environment-blocked` 跳过（不伪装通过）。
- **skipped**：2（Postgres migration）。compiler 用例在工具链不可用时按 Phase A fail-safe 跳过并打印原因。

## 10. 未运行的真实 Gate（由后续人工 Gate 控制）

- 真实 provider 生成 + Judge0 三语言端到端（Spec 005 §12.2 候选门槛：每语言 5 次 ≥4 成功）。
- 真实 Wolfram 成功 / 不可用重试 / 结果不足 ungradable。
- OCR（Stage 末/较大 diff）。
- 人工 Chrome smoke（三类课程、三语言、科学题、连续生成无重复、删除 Gate）。
- 隔离 Postgres migration test（需 `SLICE5_PG_TEST_URL`）。
- Docker test stage 全量回归 + **带编译器的稳定 test stage**（Phase A §11 验证基础设施前置：当前 Docker 镜像无 javac/g++）。

## 11. 需要 Codex 独立复核的高风险点 / 未完成项

1. **Phase F Web（§11.2）未完成**：前端 canonical contract 版本标签、science 状态 chip、错误类别分组未做。后端已通过 `interaction_spec.contract`、`science_verification`、`error_message`/稳定码提供数据；前端展示为后续专项。建议形成小范围前端任务包。
2. **Phase F eval（§11.3）未完成**：`stage4_eval` 未扩展 artifact variants / 三语言 canonical 正反例 / repair isolation / retry taxonomy / science authority / near duplicate / 零学习副作用 的 case。建议作为 eval 专项。
3. **真实 provider 根因仍需 §12.2 Gate 确认**：Java `package` 拒绝（假设 1）与单题 repair（假设 3）已消除产品侧入口，但 provider 是否仍高频产出其他非 canonical Java/C++ 形态，需真实 5×3 Gate 复核。
4. **science ungradable 与学习投影**：当前 science 未授权/不足在投影前 `return`（零投影）；建议 Codex 复核 `learning_projection` 对 short_answer `ungradable` 的既有处理是否同样零投影，保持一致。
5. **migration**：0023 仅 SQLite ORM 验证；Postgres upgrade/backfill/non-null/downgrade 须在隔离 DB 由 Codex 复跑。
6. **canonical v2 与 v1 harness 代码等价**：`_build_coding_harness` 对 v1/v2 相同（同 solve 合同），故 grader “按 harness version 分发”目前为同一代码路径；如未来 v2 harness 需差异化，须重开 ADR。

## 12. 完整 `git status --short --branch`

```text
## main...origin/main [ahead 1]
 M AGENTS.md
 M academic_companion/practice_agents.py
 M apps/api/learn_platform_api/db/models.py
 M apps/api/learn_platform_api/practice_workers.py
 M apps/api/learn_platform_api/services/practice.py
 M apps/api/learn_platform_api/services/practice_generation.py
 M apps/api/learn_platform_api/settings.py
 M apps/api/stage4_eval/runner.py
 M apps/api/tests/test_slice4_codex_correction_013.py
 M apps/api/tests/test_slice4_correction_012.py
 M docs/04-platform-stage-4-practice-memory-and-review/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_INPUTS.md
 M docs/04-platform-stage-4-practice-memory-and-review/adr/README.md
 M docs/04-platform-stage-4-practice-memory-and-review/specs/README.md
 M docs/AGENT_COLLABORATION_PLAYBOOK.md
 M docs/README.md
?? apps/api/alembic/versions/0023_add_practice_job_artifact_contract_version.py
?? apps/api/tests/test_slice5_practice_migration_postgres.py
?? apps/api/tests/test_slice5_practice_stability.py
?? apps/api/tests/test_slice5_practice_worker.py
?? artifacts/
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_GLM_BASELINE_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_GLM_HANDBACK_REPORT.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_GLM_IMPLEMENTATION_PACKET.md
?? docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_PRACTICE_STABILITY_FACT_INVENTORY.md
?? docs/04-platform-stage-4-practice-memory-and-review/adr/007-versioned-practice-artifact-validation-and-repair-authority.md
?? docs/04-platform-stage-4-practice-memory-and-review/specs/005-practice-generation-and-grading-stability.md
```

---

## 回交说明

Phase B-F 后端主体（B 版本+migration、C v2 artifact/canonical/validator、D 单题 repair+统一预算+稳定错误码+transient retry、E science 硬分界+确定性评分、F 有界去重）已完成，focused 套件 **111 passed / 2 skipped**，更广回归（含预存在修复）通过。**未完成 Phase F 的 Web 前端展示与 eval 扩展**（后端数据已就绪，建议作为后续小范围专项任务包）。

未修改旧 migration 或历史 Set/Item；只新增批准的单一列；未读取/输出 secret/原文/hidden tests；未回滚未知 dirty files；**未 commit、未 push、未运行真实 provider/Wolfram/OCR/Chrome/删除 Gate**。

按任务包 §15 在此停止。等待 Codex 独立复验（建议优先：隔离 Postgres migration、真实 provider/Judge0 三语言 Gate、OCR、带编译器的稳定 Docker test stage），并明确指示是否继续 Phase F Web/eval 专项或直接进入 Stage 4 收尾。

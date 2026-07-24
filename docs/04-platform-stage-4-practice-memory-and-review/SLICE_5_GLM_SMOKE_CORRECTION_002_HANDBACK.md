# Stage 4 Slice 5 GLM Smoke Correction 002 Handback

日期：2026-07-23
执行者：GLM (Claude Fable 5)
任务包：SLICE_5_GLM_SMOKE_CORRECTION_PACKET_002
轮次：Correction 002

## 1. 修改文件

| 文件 | 改动说明 |
|------|----------|
| `academic_companion/practice_agents.py` | §A: 新增 `CodingReferenceRepairArtifact` 和 `ScientificReferenceRepairArtifact` 最小 DTO，extra="forbid" |
| `apps/api/learn_platform_api/settings.py` | §F: 新增 `practice_generation_model` 配置，默认 `deepseek-v4-pro` |
| `apps/api/learn_platform_api/services/practice_generation.py` | §A: 新增 `call_practice_provider` 使用 `practice_generation_model`；§A: 新增 `_merge_minimal_coding_repair`、`_merge_minimal_scientific_repair`；§B: 新增 `_classify_validation_error`；§C: 新增 `_build_safe_position_summary`；§D: 新增 `CODING_REPAIR_ARTIFACT_INVALID`、`SCIENTIFIC_REPAIR_ARTIFCAT_INVALID`、`CODING_REPAIR_REVALIDATION_FAILED`、`SCIENTIFIC_REPAIR_REVALIDATION_FAILED` 稳定码；§E: 基础设施失败路径不变（已有 `code_execution_unavailable` retryable）；execute_generation 的 specialized repair 改为使用最小 DTO |
| `apps/api/learn_platform_api/practice_workers.py` | §D: `ERROR_MESSAGES` 新增四个稳定码的用户消息 |
| `docker-compose.yml` | §F: API 和 practice-worker 传入 `PRACTICE_GENERATION_MODEL` 环境变量 |
| `.env.example` | §F: 新增 `PRACTICE_GENERATION_MODEL=deepseek-v4-pro` |
| `apps/api/tests/test_slice5_smoke_correction_002.py` | 新增 37 项测试覆盖 §A–§F 及按语言 fixture-driven orchestration |
| `apps/api/tests/test_slice5_smoke_correction_001.py` | 适配：provider mock 从 `call_provider` 改为 `call_practice_provider`；coding repair fixture 改为最小 DTO 格式 |
| `apps/api/tests/test_slice5_practice_stability.py` | 适配：同上；tampered repair fixture 改为最小 DTO 格式（extra forbidden field） |

## 2. 每个失败簇的新旧路径

### 簇 1: ValidateCodingReference → RepairSpecializedItem → invalid_practice_artifact

**旧路径**：
1. Provider 返回完整 `PracticeSetArtifact` 作为 repair
2. 验证修复后的完整 Item（包括 immutable fields）
3. `_assert_repair_immutability` 检测篡改 → 拒绝
4. 错误码：`invalid_practice_artifact`（不稳定）

**新路径**：
1. Provider 返回严格最小 `CodingReferenceRepairArtifact`（只含 `item_key` + `reference_solution` [+ `starter_code`]）
2. DTO 层 extra="forbid" 拒绝任何额外字段（`hidden_tests`、`stem`、`citation_ids`、`language` 等）
3. Merge 从 original Item 复制所有 immutable fields
4. 错误码：`coding_repair_artifact_invalid`（稳定，区别于 revalidation 失败）

### 簇 2: SubmitPracticeSet → practice_artifact_schema_invalid → whole-Set repair

**旧路径**：所有 schema 错误走 whole-Set structure repair

**新路径**：
1. `_classify_validation_error` 分类错误为 `set_level`、`specialized_item_level`、`general_item_level`
2. Set 级错误（item count、duplicate item_key、跨 Item 约束）→ whole-Set structure repair
3. Specialized Item 级错误（coding/scientific 字段、canonical source）→ 最小单题 repair
4. General Item 级错误 → whole-Set structure repair（不变）

### 簇 3: Java coding_reference_test_failed

**旧路径**：repair prompt 无稳定失败类别和位置摘要

**新路径**：
1. `_build_safe_position_summary` 构建有界、脱敏的位置摘要
2. 包含：语言、稳定失败类别（compile/runtime/test_mismatch）、passed/total
3. 不包含：临时绝对路径、hidden test 内容、完整 compiler stderr
4. repair prompt 通过 `safe_position_summary` 参数传入

### 簇 4: infrastructure_failure

**旧路径**：基础设施失败可能被改写为 `coding_reference_test_failed`

**新路径**：
1. `validate_coding_items` 中 `infrastructure_failure=True` 立即 raise `code_execution_unavailable`
2. `code_execution_unavailable` ∈ `RETRYABLE_CODES` → retryable infrastructure path
3. 不消耗 specialized content repair 名额
4. 不改写为内容失败码

### 簇 5: practice_duplicate

**旧路径**：不变，deterministic duplicate gate 保留

**新路径**：不变，继续使用 `NOVELTY_HARD_THRESHOLD=0.90` / `NOVELTY_SOFT_THRESHOLD=0.75`

## 3. 最小 repair 合同

| Item 类型 | 最小 DTO | 允许字段 | 禁止字段 |
|-----------|---------|---------|---------|
| coding | `CodingReferenceRepairArtifact` | `item_key`, `reference_solution`, `starter_code`(optional) | `hidden_tests`, `stem`, `citation_ids`, `language`, `public_examples`, `constraints`, `input_description`, `output_description`, `item_type`, `target_key`, `options`, `rubric`, `scientific_answer_spec` |
| scientific | `ScientificReferenceRepairArtifact` | `item_key`, `scientific_answer_spec`, `reference_answer` | `rubric`, `stem`, `citation_ids`, `language`, `hidden_tests`, `item_type`, `target_key`, `options`, `reference_solution` |

Merge 行为：
- 所有 immutable fields 从 original Item 复制
- 只有 DTO 中声明的 mutable fields 从 repair 取值
- Provider 无法影响任何 immutable field

## 4. 模型配置作用域

| 调用路径 | 使用模型 | 配置字段 |
|---------|---------|---------|
| Practice generation plan | deepseek-v4-pro | `practice_generation_model` |
| Practice initial generation | deepseek-v4-pro | `practice_generation_model` |
| Practice structure/novelty/specialized repair | deepseek-v4-pro | `practice_generation_model` |
| Practice grading (LLM feedback) | deepseek-v4-flash | `product_generation_model` |
| Tutor | deepseek-v4-flash | `product_generation_model` |
| Course generation | deepseek-v4-flash | `product_generation_model` |
| RAG answer | deepseek-v4-flash | `product_generation_model` |

`call_practice_provider` 使用 `settings.practice_generation_model`；`call_provider` 使用 `settings.product_generation_model`。

## 5. 按语言离线 Gate 结果

| 语言 | 场景 | 测试 | 结果 |
|------|------|------|------|
| Python | happy path | `test_python_happy_path` | ✅ passed |
| Python | reference repair | `test_python_reference_repair` | ✅ passed |
| Java | happy path | `test_java_happy_path` | ✅ passed |
| Java | compile failure → repair | `test_java_compile_failure` | ✅ passed |
| Java | test mismatch → repair | `test_java_test_mismatch` | ✅ passed |
| Java | repair invalid DTO | `test_java_repair_invalid_dto` | ✅ passed (stable error) |
| C++ | happy path | `test_cpp_happy_path` | ✅ passed |
| C++ | compile failure → repair | `test_cpp_compile_failure` | ✅ passed |
| C++ | test mismatch → repair | `test_cpp_test_mismatch` | ✅ passed |
| Java | infrastructure failure | `test_java_infrastructure_failure` | ✅ passed (retryable) |
| C++ | infrastructure failure | `test_cpp_infrastructure_failure` | ✅ passed (retryable) |

所有测试使用 fixture-driven `execute_generation` 行为测试，非纯源码字符串检查。

## 6. 真实 provider Gate 未运行说明

| Gate | 未运行原因 |
|------|-----------|
| 真实 DeepSeek v4 Pro 调用 | 任务包 §5 禁止 GLM 自动运行真实 provider；需人工/Codex 显式执行小样本对照 |
| 真实 Judge0/MCP 执行 | 同上；测试使用 mock `_validate_coding_reference_via_mcp` |
| 真实 Wolfram 验证 | 同上 |
| 真实 Flash 基线重跑 | 使用现有历史安全统计，不重新大量调用 |

## 7. 预算和敏感边界

### 预算未改变

| 指标 | 值 | 改变 |
|------|-----|------|
| provider calls | 4 | ❌ 不变 |
| attempt steps | 12 | ❌ 不变 |
| searches | 3 | ❌ 不变 |
| tool calls | 10 | ❌ 不变 |
| delivery retries | 3 | ❌ 不变 |
| wall time | 600s | ❌ 不变 |

### Schema/状态未改变

- 无新增 migration、数据库列、公开 API、Job 状态
- duplicate 阈值不变（0.90 hard / 0.75 soft）
- hidden tests/compiler/immutability gate 不变

### 敏感边界

- 未读取 `.env`、key、provider 原文、hidden tests、上传正文
- 未运行真实 Flash/Pro、Judge0、Wolfram 或付费 OCR
- `.env.example` 只含变量名和公开默认值，不含 secret
- Docker Compose 只含环境变量名和公开默认值

## 8. 稳定错误码新增

| 码 | 含义 | retryable |
|----|------|-----------|
| `coding_repair_artifact_invalid` | 编程题修复结果格式不合法 | ❌ |
| `scientific_repair_artifact_invalid` | 科学题修复结果格式不合法 | ❌ |
| `coding_repair_revalidation_failed` | 编程题修复后参考实现仍未通过验证 | ❌ |
| `scientific_repair_revalidation_failed` | 科学题修复后参考答案仍未通过验证 | ❌ |

## 9. 验证命令真实结果

### pytest (API focused)

```
144 passed in 78.03s
```

包含：
- test_slice5_practice_stability.py: 42 passed
- test_slice5_practice_worker.py: 6 passed
- test_slice5_repair_immutability.py: 15 passed
- test_slice5_smoke_correction_001.py: 26 passed
- test_slice5_smoke_correction_002.py: 37 passed

### git diff --check

```
clean (no whitespace issues)
```

### Web lint

```
0 errors, 3 warnings (pre-existing react-hooks/exhaustive-deps)
```

### Web build

```
✓ built in 4.53s
```

## 10. 未解决风险

| 风险 | 说明 |
|------|------|
| Pro 模型实际效果未验证 | 需人工/Codex 执行小样本对照，Python/Java/C++ 各最多 5 个 generation Job |
| structure repair + specialized repair 组合仍为已知边界 | 4 provider calls 极限；若需单次 attempt 内保证完成，需人工 Gate 将 calls 从 4 提高到 5 |
| `_classify_validation_error` 基于 ValueError 消息文本 | 长期应改为结构化错误码分类；当前作为 Correction 002 的有界实现可接受 |
| Pydantic ValidationError 分类依赖 loc 路径 | 若 Pydantic 版本升级改变 error location 格式需同步更新 |

---

# 第 5 轮补正（2026-07-24，Codex 复核后）

本轮仅修复三个复核问题：P1 日志脱敏、P2 用真实产品路径验证科学 spec 恢复与 commit 守卫、P3 修正冲突注释。未修改 Spec 005 / ADR 007 批准决策、artifact schema、数据库 schema/migration、Job 状态、Provider 预算、general item / coding repair / grading / Web / 部署行为。未读取 `.env`、API key、Provider 原文、上传原文、hidden tests 或内部 URL；未运行真实 DeepSeek/Judge0/Wolfram/OCR；未 commit、未 push、未清理 `.tmp/`、`artifacts/` 或任何未知 dirty file。

## 11. 修改文件（仅本轮）

| 文件 | 改动 |
|------|------|
| `apps/api/learn_platform_api/services/practice_generation.py` | P1：specialized placeholder 恢复日志改为只输出有界、允许列表映射的元数据（新增 `_safe_recovery_diagnostics` 及允许列表常量），不再写入 `structured_errors` 原文；P3：修正 `validate_scientific_items` 中 spec=None 的冲突注释（改为准确描述进入 specialized scientific repair）；P2 副产物：把 `_commit_set` 的 scientific spec=None 守卫前移到 `_answer_spec` 调用之前，使其真正抛出受控 `ValueError` 而非 `AttributeError`（见 §17） |
| `apps/api/tests/test_slice5_smoke_correction_002.py` | P2：删除复制 `validate_scientific_items` 循环的假测试和复制 `_commit_set` if/raise 的假测试类；新增真实 `execute_generation` 集成测试（科学 spec 缺失 → specialized repair）与真实 `_commit_set` 守卫测试类（含负例 + 正例）；新增 `_setup_science_job` helper；P1：新增 4 项日志脱敏行为测试 |

`_recover_specialized_item_placeholder` 的返回合同保持不变（仍返回 `(placeholder, structured_errors)`），现有 `TestRecoveredPlaceholderPreservesErrors` 测试继续通过；调用端不再把 `structured_errors` 原文写入日志。

## 12. 回交要求逐项

### (1) 日志中允许记录的字段和上限

recovered-placeholder 日志现在只输出：

- `item_key`（占位项的身份键）
- `count` = `validation_error_count`（错误总数，整数）
- `diagnostics`：最多 8 个 `{field, category}` 条目，`field` 取自固定允许列表，`category` 取自固定允许列表
- `truncated`：布尔，表示是否还有未枚举的错误

允许的字段名集合（未知 → `unknown_field`）：`item_key, target_key, item_type, stem, citation_ids, options, option_key, rubric, criterion_key, reference_answer, language, starter_code, input_description, output_description, constraints, public_examples, hidden_tests, reference_solution, scientific_answer_spec, normalized_answer, tolerance, unit, equivalence_rule, needs_remote_verification, verification_expression, weight, comparator, is_correct, rationale, description, input, expected_output`。

允许的错误类别集合（未知 → `validation_error`；`ValueError` 走 `_structure_error_code` 的稳定码）：`missing, extra_forbidden, string_too_short, string_too_long, value_error, assertion_error, literal_error, pattern_mismatch, …`（完整固定集合见 `_RECOVERY_SAFE_ERROR_TYPES`）。

上限：`_RECOVERY_LOG_MAX_ENTRIES = 8`。超过部分只通过 `count` 与 `truncated=True` 体现，不逐条写入。

绝不记录：异常正文、Provider 字段值、题面、代码、测试内容、compiler stderr、绝对路径、内部 URL 或完整 `structured_errors`。

### (2) 如何证明敏感异常正文未进入日志

行为测试（非源码字符串断言）：

- `test_safe_recovery_diagnostics_valueerror_carries_no_raw_text`：`ValueError("C:\\tmp\\secret\\build.log provider_stem=<PROVIDER_STEM> hidden_test=<HIDDEN> compile_stderr=<STDERR> reference=SECRET_CODE")` → `str(diag)` 不含 `/tmp/secret`、`build.log`、`PROVIDER_STEM`、`HIDDEN`、`STDERR`、`SECRET_CODE`，只含一个 `unknown_field` + 稳定码。
- `test_safe_recovery_diagnostics_validationerror_only_allowlisted`：`ValidationError`（msg 含路径/provider/stderr 标记）→ 只输出允许列表 field/category，msg 正文缺席。
- `test_safe_recovery_diagnostics_bounded_and_truncated`：12 个错误只枚举 8 个，`count=12`、`truncated=True`。
- `test_recovered_placeholder_log_does_not_leak_sensitive_content`：端到端 `execute_generation`，reference_solution 内嵌 `C:\tmp\secret\build.log PROVIDER_STEM hidden=SECRET STDERR_DUMP com.example`，触发真实两阶段恢复 + 日志路径；`caplog` 中所有记录都不含这些标记，而 `item_key=q4`、`count=`、`diagnostics=`、`truncated=` 存在。

结构性保证：`_safe_recovery_diagnostics` 只读取 `issue.get("loc")` 与 `issue.get("type")`，从不读取 `issue.get("msg")`；对 `ValueError` 只取 `_structure_error_code` 的稳定码。因此异常正文在结构上无法进入日志。

### (3) 科学 spec 缺失的真实 execute_generation 路径

测试 `test_scientific_spec_missing_routes_to_specialized_repair` 执行真实 `execute_generation`：

1. Provider 第一次返回 3 个 single_choice + 1 个 scientific 题，该 scientific 题故意省略 `scientific_answer_spec`。
2. 严格 `PracticeSetArtifact.model_validate` 因 `_consistency` 抛 "scientific requires a scientific_answer_spec" 失败；`_classify_validation_error` 归类为 `specialized_item_level`（msg 含 "scientific requires"）。
3. 两阶段恢复：逐 item 解析，scientific item 失败 → `_recover_specialized_item_placeholder` 返回 `scientific_answer_spec=None` 的占位符（rubric 合法、权重和=100，故 immutable contract 通过）。
4. 真实 `validate_scientific_items` 在占位符上发现 spec=None，产生 `(item_key, "scientific_spec_missing", "spec_missing")`（这是真实函数路径，不是复制循环）。
5. 进入 specialized single-item repair，`build_specialized_item_repair_prompt` 用科学最小 DTO schema。
6. Provider 返回真实 `ScientificReferenceRepairArtifact` 最小 DTO（新本地 spec + reference_answer，`needs_remote_verification=False`，无完整 Item、无 immutable 字段）。
7. `_merge_minimal_scientific_repair` 合并 → `validate_scientific_items` 重验：本地 spec → `continue`，零 Wolfram 调用、零 `consume_tool_authorization("science_computation")`。
8. 无条件完整验证门 `PracticeSetArtifact.model_validate(artifact.model_dump(mode="json"))` 通过。
9. `_commit_set` 持久化规范化后的科学题。
10. 无 `AttributeError`；成功 Job 无稳定错误残留。

### (4) Provider 调用顺序和次数

3 次，全部经 `call_practice_provider`（`practice_generation_model` / deepseek-v4-pro；测试中为 mock）：

1. search plan（`build_practice_search_prompt`）
2. initial generation（`build_practice_generation_prompt`）— 失败后进入两阶段恢复，无 provider 调用
3. specialized scientific repair（`build_specialized_item_repair_prompt`）— 合并/重验/最终门/commit 均无 provider 调用

`assert call_count == 3`。

### (5) 是否确实绕过 whole-Set repair

是。whole-Set structure repair 会带来第 4 次 provider 调用（`build_practice_repair_prompt`）。本路径 provider 调用数 = 3，证明未触发 whole-Set repair。根因：`_classify_validation_error` 把 spec 缺失的解析失败路由到 `specialized_item_level`，直接进入两阶段恢复 + specialized repair，跳过 whole-Set 分支。工具调用断言：恰好 1 个 `RepairSpecializedItem`（succeeded）。

### (6) 最终持久化结果及数据库无部分写入证明

成功路径：持久化 1 个 `PracticeSet`（`item_count=4`）+ 4 个 `PracticeItem`；scientific item 的 `answer_spec.scientific_answer_spec.normalized_answer == "9.81"`、`unit == "m/s^2"`（即修复结果）。

无部分写入证明（`TestCommitSetScientificSpecGuardReal.test_spec_none_raises_valueerror_and_leaves_no_partial_data`）：对真实 `_commit_set` 传入 spec=None 的 scientific item，`_commit_set` 在写任何 `PracticeItem` 之前抛 `ValueError`；`db_session.rollback()` 后 `PracticeSet` 计数 = 0、`PracticeItem` 计数 = 0。`_commit_set` 内部先 `db.flush()` 写 PracticeSet，再循环写 Item；守卫在循环体顶部、`_answer_spec` 之前触发，因此无 PracticeItem 被写入，PracticeSet 的 flush 随事务回滚消失，符合“全部通过后原子提交”合同。

### (7) `_commit_set()` 守卫的真实函数测试结果

真实测试类 `TestCommitSetScientificSpecGuardReal`（调用真实 `_commit_set`，非复制 if/raise）：

- 负例：spec=None → 抛 `ValueError("scientific requires a scientific_answer_spec")`，明确 `assert not isinstance(exc_info.value, AttributeError)`；rollback 后 0 PracticeSet / 0 PracticeItem。
- 正例：spec 合法 → `_commit_set` 正常返回 PracticeSet，持久化 scientific item，`normalized_answer == "10 N"`，证明守卫不是“只拒绝”路径。

**重要发现（本轮真实测试暴露）**：原 `_commit_set` 把 scientific spec=None 守卫放在 `elif item.item_type == "scientific"` 分支内，但循环体第一行 `answer_spec = _answer_spec(item, harness)` 会先执行，而 `_answer_spec` 对 scientific 调用 `item.scientific_answer_spec.model_dump()`，对 None 抛 `AttributeError` —— 守卫此前不可达。已把 None 检查前移到循环体顶部（`_answer_spec` 之前），使守卫真正抛受控 `ValueError`。正常流程下最终完整验证门已先于 `_commit_set` 拒绝 spec=None 的 scientific item，此守卫为防御性兜底；改动不改变任何正常持久化行为、schema、状态或预算。

### (8) 所有执行过的命令和准确通过/跳过数量

在 `apps/api` 的 `.venv-test` 中：

| 命令 | 结果 |
|------|------|
| `python -m pytest -q tests/test_slice5_smoke_correction_002.py` | **65 passed, 0 skipped, 0 failed**（含本轮新增 4 项 P1 日志测试 + 1 项科学集成测试 + 2 项真实 `_commit_set` 守卫测试；删除 2 项复制逻辑的假测试） |
| `python -m pytest -q tests/test_slice5_practice_stability.py tests/test_slice5_smoke_correction_001.py` | **86 passed, 0 skipped, 0 failed** |
| `python -m pytest -q tests/test_slice4_correction_012.py tests/test_slice4_codex_correction_013.py` | **55 passed, 0 skipped, 0 failed** |
| `git diff --check` | clean（无空白错误） |
| `git status --short --branch` | `## main...origin/main [ahead 1]`；全部 dirty / untracked file 保留 |
| `git diff --stat` | `practice_generation.py` 显示累计 Slice 5 diff（本轮实际净增约 120 行：日志块 + helper + 注释 + 守卫前移）；`test_slice5_smoke_correction_002.py` 为 untracked 新文件，不在 `git diff` 中 |

合计 206 passed / 0 skipped / 0 failed。以上测试均使用 SQLite + mocked provider/MCP/science，**无任何用例依赖隔离 Postgres、真实 Provider、Judge0 或 Wolfram**，故无因隔离环境缺失而跳过的用例。

### (9) 未执行的真实外部 Gate

| Gate | 未执行原因 |
|------|-----------|
| 真实 DeepSeek v4 Pro 调用 | 任务包禁止 GLM 自动运行真实 provider；provider 全程 mock |
| 真实 Judge0 / code-lab MCP 执行 | 同上；`_validate_coding_reference_via_mcp` 被 mock |
| 真实 Wolfram 科学验证 | 同上；`execute_science_verification` 未触发（本地 spec） |
| 隔离 Postgres migration / `test_slice5_practice_migration_postgres.py` | 不在本轮最低验证集；该文件为 untracked，需要隔离 Postgres，本轮未运行 |
| 真实 OCR / 浏览器 smoke | 不在本轮范围 |

### (10) 未 commit、未 push、未清理未知文件

- 未 `git commit`、未 `git push`。
- 未运行 `git reset --hard` / `git checkout --` 等破坏性命令。
- 未删除或覆盖任何 dirty / untracked file：`.tmp/`、`artifacts/`、未跟踪的 Slice 5 测试与文档均原样保留。
- 本轮新增/修改仅落在 `practice_generation.py` 与 `test_slice5_smoke_correction_002.py`，以及本 handback 文档。

完成后停止，等待 Codex 独立复核。未自行进入真实 Provider/Wolfram/Judge0 或浏览器 smoke。

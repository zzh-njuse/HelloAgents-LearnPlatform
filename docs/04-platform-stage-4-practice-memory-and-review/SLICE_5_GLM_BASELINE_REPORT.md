# Stage 4 Slice 5 — Phase A 基线诊断报告

状态：Phase A 无业务改动基线诊断（GLM 第三轮回交，含 Codex 两轮复核修正）。未进入 Phase B-F。

日期：2026-07-23（初稿）；2026-07-23 第一轮修正；2026-07-23 第二轮修正（Codex 复核后）

执行者：GLM（按 `SLICE_5_GLM_IMPLEMENTATION_PACKET.md` Phase A）

本报告只新增测试/fixture 与本文件，未修改任何产品业务代码、migration、Web 或既有合同文档。所有结论只来自当前代码、本机/Docker 可重复验证，以及合成 fixture；未读取或调用真实 provider、Wolfram、Judge0、MCP 或 OCR。

## 修正记录

### 第一轮（Codex 复核阻塞项）

Codex 独立复现发现：初稿报告的 “35 passed、三语言 compiler matrix 全部通过” **不能作为已复核事实**——在本机重跑得到 28 passed / 7 failed，失败全部来自 C++ compiler matrix。根因是本机 MSYS2 `cc1plus.exe` 间歇性启动失败（退出码 `-1073741511` == `0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND`，DLL 入口点故障）；`g++ --version` 正常不代表编译链可用。初稿的测试辅助函数在编译失败时丢弃了 stderr，使 pytest 只显示笼统的 `compile_error`。

第一轮修正：

1. **保留并展示诊断信息**：Java/C++ 编译辅助函数改为返回并保留 `returncode`/`stdout`/`stderr`；`_execute` 在结果中附带截断的 `detail`。
2. **三态工具链预检**：新增 `_preflight`，明确区分 **absent / broken / ok**；`broken` 的真实编译用例以 `environment-blocked` 原因 `pytest.skip`，**不伪装通过、不冒充 harness 编译失败**。
3. **C++ 轴降级为 environment-fragile**；撤销初稿“三语言 wrapper 自洽”的强结论。
4. 新增 2 个预检回归测试，把三态分类与 fail-safe 固化为常驻护栏。

### 第二轮（Codex 复核补正项）

Codex 第二轮在宿主机与 API Docker test 镜像分别复跑，确认：

- **宿主机：29 passed / 8 skipped**。8 项 skip 全部因 C++ 工具链再次进入 `environment-blocked`（与第一轮预检设计一致，证明 fail-safe 生效）；因此“37 passed”**仍不可重复**——它只在宿主 C++ healthy 时成立。
- **API Docker test 镜像：20 passed / 17 skipped**。镜像当前**不含 `javac`/`g++`**，故 17 个 Java/C++ 真实编译用例全部 skip。镜像构建成功，但 compiler matrix 无法在其中执行。
- `_execute` 虽生成 `result["detail"]`，但多数断言仍写 `assert result["status"] == ...`，失败输出不携带该诊断。

第二轮修正（仍限 Phase A）：

5. **关键断言附 detail**：所有依赖 `_execute` 结果的关键断言改为 `assert ... , result["detail"]`（含 `result_crlf/result_fold/pass_result/fail_result/compile_result/runtime_result` 各变量），断言失败时直接打印截断 rc/stdout/stderr。
6. **脱敏宿主路径**：runner 用 `_scrub` 把编译器诊断里的宿主临时目录替换为 `<tmp>`，`detail` 不再携带宿主绝对路径（任务包 §3.4），同时保留行号/错误/列标记等诊断。
7. **据实记录多环境结果**：§5/§8 写入宿主 29/8 与 Docker 20/17，并明确“当前 Docker test stage 不具备 Java/C++ compiler Gate 条件，不是现成的稳定复跑路径”。
8. **新增 Phase B-F 验证基础设施任务**（§10）：提供带编译器的稳定 Docker/CI test stage，并禁止 compiler matrix skip——属既定稳定化范围，不需要重新 Spec/ADR Gate。

---

## 1. 当前 HEAD / branch / dirty files

| 项目 | 值 |
|---|---|
| 仓库 | `C:\Users\Admin\Desktop\HelloAgents-LearnPlatform` |
| 分支 | `main`，相对 `origin/main` ahead 1 |
| HEAD | `96a61eb7617914a2df6b35cfd2c8e3eb8aecf3e2`（`feat: complete stage 4 controlled MCP slice`，与任务包基线一致） |

`git status --short --branch` 显示的改动分为两类：

- 已知且不可回滚的已接受输入（任务包 §3.1 列明）：根 `AGENTS.md`、`docs/README.md`、`docs/AGENT_COLLABORATION_PLAYBOOK.md`、Stage 4 `README.md` / `SLICE_5_INPUTS.md` / `adr/README.md` / `specs/README.md` 的索引与状态更新；以及未跟踪的 `SLICE_5_GLM_IMPLEMENTATION_PACKET.md`、`SLICE_5_PRACTICE_STABILITY_FACT_INVENTORY.md`、`specs/005-…`、`adr/007-…`。
- 本轮 Phase A 唯一新增产物：`apps/api/tests/test_slice5_practice_stability.py`（未跟踪）与本报告。

未跟踪的 `artifacts/` 与 `.tmp/` 视为用户/Codex 既有产物，未读取其敏感内容、未清理、未纳入提交。`git diff --stat` 中没有任何产品 `.py`（services / workers / models / schemas / routers / settings）、migration、Web 或合同文档改动。未执行 reset / checkout / stash / commit / push。

## 2. 实际环境与未读取敏感配置声明

本机探测（仅版本/存在性，不含任何凭据或地址）：

| 工具 | 值 |
|---|---|
| API focused Python | `apps/api/.venv-test/Scripts/python.exe`，Python 3.13.5 |
| 本机 javac / java | 21.0.9（`javac -version` / `java -version`） |
| 本机 g++ | MSYS2 16.1.0（`g++ --version`） |

声明：本轮**未读取、未打印、未复制** `.env`、API key、provider base URL、`mcp_execution_adapter_url`、Judge0/MCP/Wolfram 私有地址、内部域名、凭据、真实 prompt、上传原文、用户答案/代码、hidden tests/reference/harness/provider 原文、日志或绝对运行路径。报告与测试快照中只有合成 fixture、聚合计数、阶段、语言、contract version、稳定错误码与命令结果。三语言 compiler 用本机工具链做快速 fixture；本机结果只能证明 wrapper/compiler 行为，**不能冒充**产品经 MCP adapter 到隔离 Judge0 的执行结果（见 §5）。

## 3. 完整链路与阶段矩阵（v1）

依据 `apps/api/learn_platform_api/services/practice_generation.py` 的 `execute_generation` / `execute_grading`、`practice_workers.run_practice_job`、`practice_type_adaptation.determine_suitability`、`academic_companion/practice_agents.py` 与 `stage4_eval/runner.py`。

### 3.1 生成链路（`execute_generation`）

```text
LessonVersion.practice_type_hints
  -> _build_lesson_learning_profile
  -> determine_suitability(code/science capability_ready + JobToolAuthorization)
  -> validate_item_type_mode(item_type_mode)            # profile_validation / type_suitability
  -> 读 prior 50 题安全摘要（去重输入）
  -> provider_step(build_practice_search_prompt)        # evidence_collection: plan, 计 1 provider call + 1 step
  -> 校验 queries(1..3)
  -> retrieve x N (<=3 searches, 各计 1 step)
  -> insufficient_evidence 则失败
  -> provider_step(build_practice_generation_prompt)    # artifact_schema: initial, 计 1 provider call
  -> PracticeSetArtifact.model_validate + citation + target + requested_types + formula + novelty
       失败 -> 最多 1 次整体结构 repair (build_practice_repair_prompt, 整份 artifact)
  -> validate_coding_items(initial):                    # coding_contract / coding_reference
       每个 coding item: consume_tool_authorization("code_execution")
         -> _validate_coding_reference_via_mcp (reference)
         starter 非空且 reference 通过 -> 再 1 次 _validate_coding_reference_via_mcp (leak)
       任一失败 -> provider_step(build_practice_repair_prompt, 整份 artifact)  # 仍是整组 repair
         -> 重验 structure + 再 validate_coding_items("repair")
         仍失败 -> ValueError("coding_reference_validation_failed")
  -> validate_scientific_items: science_computation -> execute_science_verification  # science_reference
       未通过 -> ValueError("scientific_answer_verification_failed")
  -> _assert_generation_authority                        # authority_commit
  -> _commit_set (原子写 Set/Item/Citation)
```

### 3.2 评分链路（`execute_grading`）

- `coding`：鉴权 `code_execution` -> `execute_coding_grading`（确定性分数）-> LLM 仅生成教学反馈（不改分）-> 提交 Feedback + 学习投影。
- `scientific`：先做 final-result 判定（`exact`/`numeric_tolerance` 本地；`symbolic` 经 `science_computation` Wolfram，`equivalent` 可能为 `None`）-> 把 `science_verification`（含可能为 `None` 的 `final_result_equivalent`）作为 `deterministic_verification` 交给 LLM rubric 评分 -> 提交 Feedback + 学习投影。
- `short_answer`：纯 LLM rubric 评分（一次 + 一次结构 repair）。

### 3.3 阶段矩阵（当前 error code / 是否 repair / 是否 retry / 副作用）

| 阶段 | 现有稳定码（典型） | repair | 自动 retry | provider/tool 调用 | 副作用 |
|---|---|---|---|---|---|
| profile/scope | `practice_canceled` | 否 | 否 | 0 | 零 Set |
| type_suitability | `coding_item_not_supported_by_lesson` / `science_item_not_supported_by_lesson` | 否 | 否 | 0 | 零 Set |
| evidence_collection | `insufficient_evidence` / `invalid_practice_artifact`(queries) | 否 | 否 | search-plan 1 + search ≤3 | 零 Set |
| artifact_schema/citation/target/formula/novelty | `invalid_practice_artifact` / `unknown_citation` / `invalid_learning_target` / `unsupported_practice_item_type` / `invalid_formula_content` / `duplicate_practice_item` | 最多 1 次整组 | 否 | +1 repair provider call | 零 Set |
| coding_contract/reference | `coding_reference_validation_failed` / `coding_reference_validation_infrastructure_failure` | 最多 1 次**整组** repair | 否（infra 失败也不在 `RETRYABLE_CODES`） | reference 1 + starter ≤1，repair 后再各 ≤1 | 零 Set |
| science_reference | `scientific_answer_verification_failed` | 否（直接失败） | 否 | ≤3 science/Set | 零 Set |
| authority_commit | `practice_canceled` / `source_snapshot_stale` | 否 | 否 | 0 | 晚到结果丢弃，零 Set |
| 评分 coding | `coding_grading_infrastructure_failure` / `code_execution_not_authorized` | 否 | 否（infra 不 retry） | 1 execution + 1 LLM | infra 失败零 Feedback/学习投影 |
| 评分 scientific | LLM rubric（无独立稳定码区分未授权/不可用/不足） | 1 次 repair | 否 | ≤2 Wolfram + LLM | 见 §6 假设 6 |
| 预算 | `practice_budget_exceeded` / `grading_budget_exceeded` | 否 | 否 | — | 零半成品 |

`practice_workers.RETRYABLE_CODES == {"provider_unavailable"}`：结构、reference、预算、取消、来源过期均不自动 retry（与 Spec 005 §7.1 / ADR 007 §3.6 一致，基线测试已固定）。

## 4. 六项根因假设的 confirmed / rejected / unresolved

> 判据：能由当前代码 + 本机 compiler/合成 fixture 复现的判为 confirmed/rejected；只有在真实 provider/Wolfram/Judge0 下才能定性的判为 unresolved，并给出后续最小真实 Gate case。**没有因“Java/C++ 人工成功率为 0”而预先确认任何一项。**

### 假设 1：provider/validator/wrapper/Judge0 canonical source 不一致 — **部分 confirmed，部分 unresolved**

- **confirmed（产品侧，可复现）**：Java `package` 声明被 v1 Pydantic validator **接受**（只校验 `class Solution` 与 `static String solve(String)`，不校验 `package`），但 harness 在 source 之前拼接 `import java.io.*; import java.util.*;`，使 `package foo;` 不再是首行 → **javac 编译失败**。即“validator 接受、wrapper/compiler 拒绝”的 canonical 不一致。基线测试 `test_v1_java_package_passes_validator_but_breaks_harness_compile` 用本机 javac 复现。这是**与 provider 无关**的系统性 Java 失败入口：provider 若反射性带 `package`，则结构校验通过、reference 校验 `compile_error`、触发整组 repair、大概率仍带 `package` 再失败 → `coding_reference_validation_failed`。
- **confirmed（一致性正向）**：对 canonical 形态，validator↔wrapper↔本机 compiler 三者一致——`public class Solution` 被 harness 规范化为 `class Solution`；C++ `string`/`std::string` 拼写、provider 自带 `#include`/`using namespace std;` 均被接受并编译通过；Java `Main`/`main`、非 static `solve`、C++ `main`、C++ by-value `string solve(string)` 被 validator 正确拒绝（见对应参数化测试）。
- **unresolved（需真实 provider/Judge0）**：(a) 真实生成 provider 是否高频产出 `package`/非 static/by-value 等非 canonical 形态；(b) 隔离 Judge0 与本机 compiler 的字符集/换行/`String.valueOf(null)` 等行为是否一致。后续最小真实 Gate：在 require_coding 的 Java 课节连跑 5 次，trace 中稳定码与 `AgentToolCall.error_code` 落在 `compile_error` 类，并保留脱敏的 reference 修复轮次。

### 假设 2：repair 信息不足（分类过粗） — **rejected（结构性主张），有效性 unresolved**

- **rejected**：coding repair 确实把稳定分类传给 provider——`validation_issues` 形如 `"{item_key}: reference {categories}"`，`categories` 来自 `CodingReferenceValidationResult.error_categories`（`compile_error`/`runtime_error`/`timed_out`/`output_limited`/`test_mismatch`/`harness_output_parse_error`）。“provider 不知道是 compile/runtime/test mismatch”的主张与代码不符。
- **有效性 unresolved / 实际由假设 1、3 主导**：repair 仍缺少 Spec 005 §6.3 要求的“有界位置摘要”，且作用域是整组（见假设 3）；真正让 repair 失败重复的是未处理的 `package`（假设 1）与整组重写（假设 3），而非“没有分类”。是否更细的位置摘要能在真实 provider 上提升成功率，需真实 provider Gate。

### 假设 3：整组 repair 放大失败 — **confirmed**

- 行为测试 `test_v1_coding_reference_failure_repairs_whole_set_not_just_failed_item` 证明：单个 coding item 的 reference 失败时，`execute_generation` 把**整份 artifact**（含已合法的 single_choice item）交给 `build_practice_repair_prompt` 重新生成，而非只修失败 item。这会重新生成合法题、citation 与题数，放大 schema/duplicate/预算连锁失败概率，也使前后成功率难以归因。与 Spec 005 §5 / ADR 007 §3.3“只修失败 Item”冲突。

### 假设 4：预算口径冲突 — **confirmed**

- **双 step 口径**：运行时 `provider_step` 用 `practice_generation_max_attempt_steps=20` 作硬上限；而 `stage4_eval/runner.py` 断言 `run.step_count <= practice_generation_max_steps(6)`。一条 plan+search+submit+reference+starter+repair 的 coding 生成合理达到 6–7 步，eval 会把**合法运行时路径**标为 `step budget exceeded`。
- **死配置**：`practice_coding_max_ref_calls=1` 定义后从未被运行时读取（grep + `inspect.getsource` 证实 `practice_generation` 不引用它）。实际 per-Set 工具预算是 `practice_generation_max_tool_calls=10`，经 `practice.create_generation_job` 写入 `JobToolAuthorization.max_calls`，由 `consume_tool_authorization` 强制。
- 以上构成“同一预算的多套口径”，正是 Spec 005 §7 / ADR 007 §3.6 要收敛为单一权威 counter 的对象。基线测试 `test_v1_has_dual_step_budget_denomination`、`test_v1_coding_reference_call_budget_setting_is_dead_config` 固定。

### 假设 5：自动化代表性不足 — **confirmed（基线层面）**

- 既有测试（含 `test_slice4_codex_correction_013.py` 的若干 harness 用例）只检查 harness 字符串**形状**（包含 `solve(...)` 标记、`numeric_tolerance` 文本、`public class` 被规范化），未把三语言真实 compile/run matrix 作为硬门禁。本轮新增 `test_slice5_practice_stability.py` 才首次用本机 javac/g++/python 真实编译执行 harness，覆盖正例、compile/runtime error、test mismatch、空输入、Unicode、CRLF/多行/空白折叠、numeric tolerance 边界、加权部分分等（见 §5、§9）。eval 的 6-step 口径同时让典型 coding 运行被误判（与假设 4 叠加）。

### 假设 6：科学题 deterministic evidence 不完整仍被 LLM 评分 — **confirmed（结构性缺口），实际误判 unresolved**

- **confirmed（评分路径结构缺口）**：`execute_grading` 的 `scientific` 分支中，`exact`/`numeric_tolerance` 可本地判定；`symbolic` 在“未授权 / 预算耗尽 / 工具不成功 / observation 非 bool”任一情况下，`equivalent` 保持 `None`，随后仍以 `deterministic_verification={"final_result_equivalent": None, ...}` 进入 LLM rubric 评分。系统 prompt 仅口头要求“不要把 None 当唯一依据”，但**没有硬分界**把“未授权/不可用/结果不足”分别收敛为 `ungradable`（score null）/ Job retry / 零学习投影。这与 Spec 005 §10.2 / ADR 007 §3.5 要求的硬分界冲突。
- **unresolved（实际误判）**：LLM 在 `equivalent=None` 时是否真的给出不当数值分，需真实 provider/Wolfram 才能定性。后续最小真实 Gate：构造一个 symbolic 科学题、关闭 science 授权或让 Wolfram 返回不足 observation，断言 Feedback 为 `ungradable`、`score is None`、零学习投影。

## 5. 三语言 compiler matrix 与产品 MCP probe 结果

### 5.1 多环境实测结果（关键）

`test_slice5_practice_stability.py` 共 37 用例，其中 17 个依赖真实 Java/C++ 编译器（7 个 java 参数化 + 2 个 java 独立 + 8 个 cpp）。三态预检决定它们是“执行”还是“environment-blocked 跳过”。实测：

| 环境 | passed | skipped | 说明 |
|---|---:|---:|---|
| 宿主机（GLM 会话，C++ healthy） | 37 | 0 | 仅在宿主 C++ 恰好可用时成立，**不可重复** |
| 宿主机（Codex 复核，C++ 再次损坏） | 29 | 8 | 8 个 C++ 真实编译用例 `environment-blocked` 跳过 |
| API Docker test 镜像 | 20 | 17 | 镜像**无 `javac`/`g++`**，17 个 Java/C++ 用例全部跳过 |

由表可见：**“37 passed”不是稳定事实**；稳定可重复的部分是“非编译用例（20）恒通过 + Java/C++ 用例随工具链可用性而执行或跳过”。聚合的“语言 × 用例”结论（下表）只在对应语言工具链 `ok` 时成立：

| 用例 | python | java | cpp |
|---|:-:|:-:|:-:|
| canonical 正确 reference（identity/upper/reverse） | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过（见 5.1.1） |
| 空输入 / Unicode(Latin+CJK) | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| 空白折叠 / 多行 / CRLF 规范化 | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| numeric tolerance 边界（内/外） | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| 加权部分分 | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| Java `public class` 规范化 | n/a | ✅ healthy 时通过 | n/a |
| C++ `string` 拼写 + provider includes | n/a | n/a | ✅ healthy 时通过 |
| compile error 分类 | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| runtime error 不冒充通过 | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| 代表性错误解不全过 | ✅ 已验证 | ✅ healthy 时通过 | ✅ healthy 时通过 |
| **Java `package` 声明**：validator 通过、harness 编译失败 | n/a | ❌ confirmed 缺陷 | n/a |

> “已验证”= 在所有环境（含 Docker）都执行并通过（纯 Python，无外部编译器）；“healthy 时通过”= 仅在该语言编译器预检 `ok` 时执行。

#### 5.1.1 C++ 工具链 intermittency 与 Docker 缺编译器（撤销初稿强结论）

两轮独立复核揭示两个**环境侧**问题（均非产品缺陷）：

1. **宿主 MSYS2 C++ 间歇性损坏**：`cc1plus.exe` 启动失败，退出码 `-1073741511`（== `0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND`，DLL 入口点解析失败）。GLM 会话恰好 healthy（25/25 平凡编译 + 37 passed），Codex 复核时再次损坏（29 passed / 8 skipped）。
2. **API Docker test 镜像无 `javac`/`g++`**：Codex 构建镜像成功并在其中复跑，得到 20 passed / 17 skipped——Java/C++ 真实编译用例因编译器不存在全部 skip。**因此当前 Docker test stage 不具备 Java/C++ compiler Gate 条件，不能描述为现成的稳定复跑路径。**

判定：

- Java/C++ = 0 的根因判断保持不变：**不是静态 wrapper bug**（canonical 形态在 healthy 工具链下三语言自洽），而是上游 provider 非 canonical 形态（尤其 Java `package`）+ 整组 repair + 预算口径。C++ 未发现等价于 Java `package` 的静态不一致（provider 自带 `#include`/`using namespace` 被容忍）。
- 结论降级：**Python 在本机与 Docker 均已验证；Java/C++ “工具链 healthy 时自洽”，但宿主 C++ 间歇损坏、Docker 无编译器 → Java/C++ 轴 environment-fragile**。
- 要把 Java/C++ 轴计入正式 Gate 事实，**须先交付“带编译器的稳定 Docker/CI test stage 并禁止 compiler matrix skip”（Phase B-F 验证基础设施，见 §10）**；当前本机/Docker 结果仅作快速 fixture。

fail-safe 已就位：`_preflight` 对 absent/broken 返回并 `pytest.skip`（带截断、脱敏的 rc/stderr）；两个回归测试固化三态分类（见 §9）。即使工具链不可用，Java/C++ 用例也显式 skip 并打印原因，**既不伪装通过、也不塌缩为空 compile_error**。

### 5.2 产品 MCP / Judge0 probe — **未运行（按 §6.2 跳过并说明）**

- 未直接 curl Judge0，也未经产品 MCP adapter 发起真实 `run_code`。原因：该 probe 需要 `settings.mcp_execution_adapter_url`（内部/敏感地址）与运行中的 Compose + 隔离 Judge0 VM，且 Phase A 禁止读取 secret/URL。
- 因此本机 compiler matrix 是 §6.2 的“快速 fixture”基线；正式三语言 Judge0 集成证据留给后续经确认的真实 provider/Judge0 Gate（任务包 §3.3、Spec 005 §12.2）。本机 compiler 与 Judge0 的字符集/换行/`String.valueOf(null)` 等差异仍属 unresolved（见假设 1）。
- 注意：Codex 第二轮构建并运行了 **API Docker test 镜像**（不是 Judge0 probe）——那是 §5.1 的 compiler matrix 在容器内的运行，因镜像无编译器而 17 项 skip，与 Judge0 无关。

## 6. 当前错误 / repair / retry / 预算冲突汇总

1. **Java `package` canonical 不一致**（假设 1，confirmed）：validator 接受、harness 编译失败 → 系统性 Java reference 失败入口。
2. **整组 repair**（假设 3，confirmed）：单个 coding/science 失败重写整份 Set，重生成合法题与 citation，放大连锁失败。
3. **预算多口径**（假设 4，confirmed）：运行时 20-step vs eval 6-step；`practice_coding_max_ref_calls` 死配置；per-Set 工具预算实际由 `practice_generation_max_tool_calls=10` 经 `JobToolAuthorization` 强制。
4. **科学评分无硬分界**（假设 6，confirmed 结构缺口）：`equivalent=None` 仍进 LLM rubric，未按未授权/不可用/不足分别收敛为 `ungradable`/retry/零投影。
5. **自动化只查 harness 形状**（假设 5，confirmed 基线层面）：本轮才补齐真实 compiler matrix；eval 6-step 会误判合法 coding 运行。
6. **repair 分类并非缺失**（假设 2，rejected）：分类已传入；不足在于无有界位置摘要 + 整组作用域（归入 1/3）。
7. **Job 无 artifact contract 版本列**（ADR 007 §3.9）：v1 `PracticeJob` 无 `artifact_contract_version`（基线测试固定其缺失），失败/retry 中 Job 无版本 snapshot，部署默认切换可能静默换合同 → Phase B 单列加法 migration 的依据。

retry 现状（与 Spec 005 一致，需保持）：仅 `provider_unavailable` 自动 retry；结构/reference/预算/取消/来源过期不 retry。

## 7. 建议修改文件与为何符合 Spec/ADR（仅建议，Phase A 不实施）

| 方向 | 涉及文件（建议） | 依据 |
|---|---|---|
| v2 artifact/harness 与 v1 兼容读取 | `academic_companion/practice_agents.py`、`apps/api/learn_platform_api/services/practice_generation.py`、`practice_type_adaptation.py` | Spec 005 §6；ADR 007 §3.1/§3.4 |
| 拒绝 Java `package`/规范化 canonical（修假设 1） | `practice_agents.py`（validator）、`practice_generation.py`（harness/prepend 顺序） | Spec 005 §6.2；ADR 007 §3.4 |
| 单题 repair 只替换失败 Item（修假设 3） | `practice_generation.py`、`practice_agents.py`（repair artifact） | Spec 005 §5；ADR 007 §3.3 |
| 单一权威 step counter + 移除死配置（修假设 4） | `settings.py`、`practice_generation.py`、`stage4_eval/runner.py` | Spec 005 §7；ADR 007 §3.6 |
| 科学评分硬分界（修假设 6） | `practice_generation.py`（execute_grading scientific）、错误码 | Spec 005 §10.2；ADR 007 §3.5 |
| 新增 `practice_jobs.artifact_contract_version` migration | 新增 alembic 增量（当前 head 之后）、`db/models.py` | ADR 007 §3.9（Phase B） |
| 三语言真实 compiler/runtime matrix 进硬门禁 | `tests/test_slice5_practice_stability.py`（本轮已建基线） | Spec 005 §12.1；ADR 007 §3.4 |

以上均为 Phase B-F 范围，**本轮不实施**。Java `package` 的修复落在通用 validator/canonical 合同（非课程/关键词特判），符合 AGENTS.md“禁止硬编码”与 Spec 005 §6.2。

## 8. 所有命令、结果与未运行原因

已运行（本机 venv `apps/api/.venv-test/Scripts/python.exe`，Python 3.13.5）：

```text
git status --short --branch            # main ahead 1；仅新增本测试+报告+已知 dirty 文档
git rev-parse HEAD                     # 96a61eb...（与任务包基线一致）
git diff --stat                        # 无产品 .py / migration / Web / 合同文档改动
git diff --check                       # 干净（仅既有 CRLF warning）

# 多环境实测（37 用例；17 个依赖真实 Java/C++ 编译器）
# 宿主机（GLM 会话，C++ healthy）：    37 passed / 0 skipped   —— 仅 healthy 时，不可重复
# 宿主机（Codex 复核，C++ 再次损坏）： 29 passed / 8 skipped   —— 8 个 C++ 用例 environment-blocked
# API Docker test 镜像（无 javac/g++）：20 passed / 17 skipped  —— 17 个 Java/C++ 用例全 skip
python -m pytest tests/test_slice5_practice_stability.py -q -p no:cacheprovider
python -m pytest tests/test_slice4_codex_correction_013.py tests/test_slice5_practice_stability.py -q -p no:cacheprovider
                                       # 回归 30 passed（Codex 已独立确认）

# C++ 工具链 stress（平凡编译 25 次，GLM 会话 healthy）：25/25 rc=0；Codex 复核时 cc1plus 再次 -1073741511
g++ -std=c++17 -fexec-charset=UTF-8 _s.cpp -o _s.exe

# fail-safe 验证（monkeypatch 模拟 cc1plus -1073741511，两个回归测试）
#   test_preflight_classifies_absent_compiler                         -> absent
#   test_preflight_classifies_broken_compiler_and_blocks_real_compile -> broken + environment-blocked skip
# detail 脱敏验证：失败断言 detail 现打印 stage=g++ rc=1 stderr=<tmp>\harness.cpp:7:58: error: ...（无宿主路径）
```

**关于 “N passed” 的更正（两轮）**：

- 初稿“35 passed、三语言自洽”不可重复：Codex 同机复现 28 passed / 7 failed（C++ `cc1plus -1073741511`）。
- 第一轮修正后“本会话 37 passed”仍不可重复：Codex 第二轮宿主机 29 passed / 8 skipped（C++ 再次损坏，预检按设计跳过）。
- Codex 第二轮在 API Docker test 镜像复跑得 20 passed / 17 skipped（镜像无 `javac`/`g++`）。
- **稳定可重复的事实**：非编译用例（20）在宿主与 Docker 均通过；Java/C++ 用例随工具链可用性而执行或跳过；Slice 4 回归稳定 30 passed。

未运行及真实原因：

- **产品 MCP/Judge0 probe**：需 `mcp_execution_adapter_url`（敏感）+ 运行 Compose/VM；Phase A 禁止读 secret/URL（§5.2）。
- **真实 provider/Wolfram/OCR/Chrome/删除 smoke**：均由后续人工 Gate 控制（任务包 §3.3、§13.4、§14）。
- **API Docker test stage**：Codex 第二轮已构建并运行（build 成功），得 **20 passed / 17 skipped**——镜像**无 `javac`/`g++`**，Java/C++ matrix 无法在其中执行（§5.1.1）。当前 Docker test stage **不具备** Java/C++ compiler Gate 条件；带编译器的稳定 test stage 列为 Phase B-F 验证基础设施（§11）。
- **API 全量 pytest**：本轮未改产品代码，未跑全量。
- **Postgres migration test**：Phase A 不新增 migration（§7 列为 Phase B），未运行。
- **修复本机 MSYS2 工具链**：`cc1plus -1073741511` 属宿主 DLL 环境问题；Phase A 不改动宿主环境/PATH/安装，改为在测试层用预检 + stderr 捕获如实暴露与降级（§5.1.1）。

无 skip/timeout 被伪装为通过：工具链 absent/broken 时真实编译用例以 `environment-blocked` 原因 `pytest.skip` 并打印截断、脱敏 rc/stderr（两个预检回归测试固定该行为）。Codex 宿主复跑 8 skip、Docker 复跑 17 skip 均为该机制产生的如实跳过，**非伪装通过**。

## 9. 新增测试文件

`apps/api/tests/test_slice5_practice_stability.py`（**37 用例**，本会话 healthy 时全部通过）：

1. 三语言真实 compiler/runtime matrix（参数化 × python/java/cpp）：canonical 正确、Unicode、空输入、空白/多行/CRLF 规范化、numeric tolerance 边界、compile/runtime error 分类、代表性错误解不全过、加权部分分；Java `public class` 规范化、C++ `string` 拼写 + provider includes。
2. **工具链预检护栏（本轮新增）**：`test_preflight_classifies_absent_compiler`、`test_preflight_classifies_broken_compiler_and_blocks_real_compile`——固化 absent/broken/ok 三态分类，确保 `cc1plus -1073741511` 这类“存在但无法启动”的损坏链被 `environment-blocked` 跳过、不伪装通过、不塌缩为空 `compile_error`。
3. validator↔harness 一致性：`test_v1_java_package_passes_validator_but_breaks_harness_compile`（confirmed 缺陷，断言带 stderr 详情，且预检保护避免损坏 javac 冒充该结果）；参数化拒绝 Java `Main`/非 static、C++ `main`/by-value。
4. 静态画像：双 step 预算口径（6 vs 20）、`practice_coding_max_ref_calls` 死配置、retry 仅 `provider_unavailable`、`PracticeJob` 无 `artifact_contract_version`、coding 版本钉死 `solve_utf8_string_v1`。
5. 行为：`test_v1_coding_reference_failure_repairs_whole_set_not_just_failed_item`（confirmed 整组 repair）。

辅助函数改造：`_run_{python,java,cpp}_harness` 现返回 `status/stage/returncode/stdout/stderr` 字典；`_execute` 在结果中附截断 `detail`；**所有依赖 `_execute` 的关键断言改为 `assert ... , result["detail"]`**（含各 result 变量），断言失败时直接可见 rc/stdout/stderr；`_scrub` 把诊断里的宿主临时目录替换为 `<tmp>`，`detail` 不携带宿主绝对路径；`_preflight` + `_require_toolchain_ok` 实现三态门禁。

均为 characterization 基线：断言**当前 v1 行为**，使假设 1/3/4/5/6 的缺口由可运行证据固定；Phase B-F 修复后相应断言会翻转并需同步更新。无任何用例读取 secret、原文或依赖真实 provider/MCP。

## 10. 是否发现需要额外 schema / 状态 / 预算 / 范围

- **schema**：未发现需超出 ADR 007 §3.9 已批准的单一列 `practice_jobs.artifact_contract_version`。v1 失败/低分投影的缺口可由细化稳定 error code + 安全 trace 表达，不需新表/新状态（与 Spec 005 §1、ADR 007 方案 F 一致）。**未触发任务包 §14 的“停下重新 Gate”条件。**
- **状态**：现有 `queued|running|retry_wait|queue_failed|cancel_requested|canceled|succeeded|failed` 足够；运行中无法可靠投影精确阶段时按 Spec 005 §4.1 显示“生成与验证中”，不需新状态机。
- **预算**：需把多口径收敛为单一权威 counter（Spec 005 §7），属配置/实现统一，非提高量级，**不需重新 Gate**。
- **范围**：未发现需新增第三项 MCP、动态 Tool、新题型、多 specialized item 或提高真实成功率门槛。Java `package` 修复属通用 canonical 合同，不构成范围扩张。

## 11. Phase B-F 验证基础设施前置（不需要重新 Spec/ADR Gate）

两轮复核暴露的**环境侧**缺口（宿主 C++ 间歇损坏、Docker test 镜像无编译器）使 compiler matrix 目前无法在任何单一环境稳定执行。把下列项列入 Phase B-F 验证基础设施（属 Spec 005 §12.1 / ADR 007 §3.4 的既定稳定化范围，**不构成 schema/预算/评分权威变更，不需要重新 Gate**）：

1. **提供带编译器的稳定 Docker/CI test stage**：在 API test 镜像（或专用 ci stage）安装 `openjdk`/`g++`（与产品 Judge0 runtime 对齐的版本），使 Java/C++ matrix 可在容器内确定性执行，摆脱宿主 MSYS2 intermittency。
2. **在该 stage 禁止 compiler matrix skip**：稳定环境建成后，移除/收紧 `_preflight` 对 Java/C++ 的 `environment-blocked` 容忍，使 compiler matrix 成为硬门禁（CI 中 compiler 缺失=失败，而非 skip）。
3. 复跑后把 Java/C++ 轴从 environment-fragile 升级为正式 Gate 事实，并据此校准本报告 §5 的“healthy 时通过”结论。

在交付该基础设施前，Java/C++ matrix 的产品侧结论（无静态 wrapper bug；canonical 形态自洽；Java `package` canonical 不一致；整组 repair；预算多口径）由代码可读 + healthy-时实测共同支持，但“三语言 compiler matrix 全绿”不作为已复核事实。

---

## 回交说明（第三轮回交，含 Codex 两轮复核修正）

本轮针对 Codex 第二轮补正项完成修正（仍限 Phase A）：

- **关键断言附 detail**：所有依赖 `_execute` 结果的断言改为 `assert ... , result["detail"]`，失败时直接打印截断 rc/stdout/stderr（已用 g++ 真实 compile_error 验证 detail 含 `<tmp>\harness.cpp:7:58: error: ...`）；
- **脱敏宿主路径**：`_scrub` 把编译器诊断里的宿主临时目录替换为 `<tmp>`，`detail` 不携带宿主绝对路径（任务包 §3.4）；
- **据实记录多环境结果**：§5/§8 写入宿主 29 passed/8 skipped、Docker 20 passed/17 skipped，并明确“当前 Docker test stage 不含 `javac`/`g++`，不是现成的稳定复跑路径”；
- **新增 Phase B-F 验证基础设施任务**（§11）：提供带编译器的稳定 Docker/CI test stage 并禁止 compiler matrix skip——属既定稳定化范围，不需要重新 Spec/ADR Gate。

Phase A 现状：独立 Slice 5 基线测试 **37 用例**（稳定可重复部分 = 非编译 20 用例全过；Java/C++ 用例随工具链可用性执行或 skip）+ 本报告；调查了 Java/C++ 为 0 及完整生成/评分链路，逐项给出六假设的 confirmed/rejected/unresolved 与证据。**未修改任何产品业务代码、migration、Web 或合同文档；未读取/输出敏感配置与原文；未回滚未知 dirty files；未 commit/push。**

按任务包 §6.5，**在此停止，不进入 Phase B-F**。等待 Codex 再次独立复核本报告、`git diff` 与多环境重跑结果，并明确回复“继续 Phase B-F”或发进一步修正指令后再按同一任务包恢复。

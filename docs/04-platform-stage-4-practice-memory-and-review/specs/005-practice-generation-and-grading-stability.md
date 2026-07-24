# Spec 005：练习生成与评分链路稳定化

状态：已于 2026-07-23 通过人工 Gate，可生成正式 GLM 基线诊断与实现任务包

日期：2026-07-23

## 1. 评审结论摘要

Slice 5 不新增题型、MCP capability 或学习功能。它把既有普通题、Python/Java/C++ 编程题和科学题收敛成一条可诊断、可修复、可度量的可靠链路。

建议采用 `practice_artifact_v2` 与 `solve_utf8_string_v2`：新生成题使用明确版本；旧 Set/Item 保持原样可读，并继续由 v1 grader 评分，不回填、不批量迁移。生成验证按固定阶段执行，结构修复、reference 修复和基础设施 retry 分开计数；失败必须返回阶段化稳定错误，不以增加无限重试提高表面成功率。

建议不新增表和 Job 状态，只做一个加法 migration：`PracticeJob` 在创建时固定 `artifact_contract_version`，旧行回填 v1。成功 Set/Item 继续使用现有 `generation_config` 与 `answer_spec/interaction_spec` 保存版本；失败阶段由细化 error code 和安全 trace 表达。除此之外若实现需要新字段或表，必须先修订 ADR 007 并重新 Gate，而不是让 GLM 自行扩 schema。

## 2. 已验证事实、本次建议与待选项

| 类型 | 内容 |
|---|---|
| 已验证事实 | Judge0 三语言和 MCP schema/readiness 已通过 Slice 4 真实 smoke；工具可用不等于 artifact 可发布 |
| 已验证事实 | 当前 Java/C++ 真实生成成功率被用户观察为 0，但本轮未独立重跑，根因仍待分段复现 |
| 已验证事实 | 当前测试覆盖 harness 形状和失败零持久化，但未把真实三语言 compiler/runtime matrix 作为硬门禁 |
| 本次建议 | 新 artifact/harness 使用 v2；旧 v1 只读兼容，不迁移、不重新验证历史题 |
| 本次建议 | 每个 Set 最多一个专业题（`coding` 或 `scientific`），其余为普通题，避免整组工具预算放大 |
| 本次建议 | 精确重复硬拒绝；可解释近重复按同 target/type/task signature + 高字符 n-gram 相似度处理，不引入新向量事实源 |
| 待人工选择 | 是否接受 v2、最小 Job 版本 migration、分层预算、错误码和真实 provider 成功率门槛 |

## 3. Goal / Context / Constraints / Done when

| 项目 | 内容 |
|---|---|
| Goal | 稳定完成“课节画像 -> 适配 -> 生成 -> 验证 -> 发布 -> 作答 -> 确定性评分/受控反馈”，并能定位每类失败 |
| Context | Slice 1-4 已有不可变 Practice、Job/queue/trace、三语言 execution、Wolfram、学习投影和删除权威 |
| Constraints | 不硬编码材料/关键词/答案；不泄露 hidden facts；Postgres 权威；失败零伪成功；不扩大 MCP/Memory/Mastery 范围 |
| Done when | 自动化矩阵、真实 provider/Judge0/Wolfram smoke、错误投影、取消/删除/晚到结果、Web 与 Stage 4 最终 Gate 全部通过 |

## 4. 用户路径与产品行为

### 4.1 生成

1. 用户在当前已发布 Lesson Version 选择自动、普通、要求编程或要求科学题。
2. 系统先读取该 Lesson Version 的结构化 objective/evidence hints 和 capability/authorization snapshot。
3. `require_*` 材料不适合时在 provider 调用前失败；`auto` 只保留真正支持的题型。
4. Job 就近显示安全进度：已有权威 trace 足够时显示准备依据、生成、校验题目、验证参考解/科学答案或发布；运行中无法可靠投影精确阶段时显示“生成与验证中”，不为实时进度新增第二套状态机或额外 schema。
5. 全部题通过后才原子发布 Set；任何阶段失败均为零 Set/Item 持久化。

### 4.2 编程作答

1. 新 v2 coding item 明确显示语言、固定 `solve` 合同、公开示例、限制和 starter。
2. 学生代码只与该 Item 的不可变 tests/harness version 组合执行一次正式评分。
3. 分数只由测试权重决定；compile/runtime/timeout/output-limit 是学生程序结果，不是基础设施失败。
4. LLM 只读取最小代码与脱敏测试摘要生成教学反馈；provider 失败不丢失确定性分数。
5. 基础设施失败时不产生 0 分或 Learning Event，Job 进入有限可重试失败。

### 4.3 科学作答

1. 题目必须包含规范答案、完整 worked solution、rubric、容差、单位/等价规则和 verification provenance。
2. exact/numeric 且本地规则充分时零 Wolfram 调用。
3. symbolic 或明确需要远程验证时，只有授权、ready、schema 和预算都有效才调用。
4. 未授权时返回无分数 `ungradable`；临时工具不可用时 Job 可重试且不提交 Feedback；工具成功但 observation 不足时返回无分数 `ungradable`。
5. LLM 必须评价推导步骤，不能用“最终值相同”代替过程评分，也不能填补缺失的确定性验证。

## 5. 可靠性流水线

每个 Generation Job 按以下顺序执行并记录一个安全阶段结果：

| 顺序 | 阶段 | 成功条件 | 失败副作用 |
|---:|---|---|---|
| 1 | `profile_validation` | objective、evidence hint、版本与 scope 完整 | 零 provider/tool/Set |
| 2 | `type_suitability` | 请求题型受材料、授权和 capability 支持 | 零 provider/tool/Set |
| 3 | `evidence_collection` | 固定 snapshot 内有足够、可回读证据 | 零 Set |
| 4 | `artifact_schema` | 数量、题型、target、citation、formula、私有字段完整 | 最多一次整份结构 repair |
| 5 | `novelty_validation` | 无 exact 或受控 near duplicate | 最多一次定向改题 repair |
| 6 | `coding_contract` | v2 source/starter/tests 可规范化且无入口冲突 | 最多一次单题 repair |
| 7 | `coding_reference` | reference 在真实 canonical harness 通过全部 tests | 最多一次单题 repair |
| 8 | `science_reference` | answer spec、worked solution 与所需验证一致 | 最多一次单题 repair |
| 9 | `authority_commit` | owner/lease/scope/source/cancel/delete 均仍有效 | 晚到结果丢弃，零 Set |

repair 只替换失败的 Item artifact；合法普通题、citation ledger、题数、目标和其他题不重新生成。修复后必须重跑该 Item 的全部后续 Gate，不能只跳过失败断言。

## 6. `practice_artifact_v2` 合同

### 6.1 共同规则

- Set 的 `generation_config.artifact_contract_version` 固定为 `practice_artifact_v2`。
- 每个 Item 必须有一个目标、至少一个可回读 citation 和稳定 item type。
- specialized item 每 Set 最多一个；题数大于 1 时至少一个普通题。
- provider artifact 不携带数据库 ID、harness source、tool endpoint 或运行配置。
- validator 接受集合必须与 prompt/schema、持久化投影和 grader dispatcher 完全一致。

### 6.2 三语言 canonical 合同

| 语言 | provider/reference 入口 | 产品 wrapper | 禁止 |
|---|---|---|---|
| Python | `def solve(input_text: str) -> str`（类型标注可省） | 产品添加测试 runner | `__main__`、I/O 副作用、依赖安装 |
| Java | 非 public `class Solution` + `static String solve(String input)` | 产品生成唯一 `Main` | provider 自带 `Main/main`、package、外部依赖 |
| C++ | `std::string solve(const std::string& input)`；允许等价 `string` 写法 | 产品添加 includes、namespace 与唯一 `main` | provider 自带 `main`、外部库、文件/网络 |

v2 validator 可以规范化无语义差异的 Java `public class Solution` 和 `std::string/string` 拼写，但不得猜测或改写算法。编译前生成物必须通过长度、入口唯一性和禁止能力检查。

tests 对三语言共享同一 UTF-8 string 输入/输出、规范化文本比较和显式数值容差语义。空输入、Unicode、CRLF/LF、多行输出和浮点边界必须进入真实 compiler/runtime matrix。

### 6.3 reference 与 starter

- reference 必须在一次 canonical execution 中通过全部 public + hidden tests。
- starter 可以为空；非空时必须通过静态入口/泄露检查。
- starter 的行为性泄露检查是独立、显式预算项，不再冒充 reference call；是否执行由 starter 是否足以编译决定。
- reference repair 只能收到语言、contract version、`compile|runtime|timeout|output_limit|test_mismatch|harness_output` 分类和有界位置摘要；不得收到 hidden input/output、harness、远端原文或 reference 全文回显。
- 代表性错误解必须不能通过全部 tests；这是 eval Gate，不要求 generation 期为每题额外调用模型。

## 7. 修复、retry 与预算

### 7.1 三种机制不得混淆

| 机制 | 适用 | 不适用 |
|---|---|---|
| artifact repair | provider JSON/schema/citation/formula/duplicate/canonical item 错误 | 网络、队列、MCP 不可用 |
| reference repair | reference compile/runtime/test 或 science spec/verification 不一致 | 扩大题意、换资料、增加题数 |
| delivery retry | provider transport、queue、MCP 临时基础设施、lease recovery | 结构错误、材料不适合、学生代码错误、预算耗尽 |

### 7.2 候选硬预算

| 项目 | v2 上限 |
|---|---:|
| search-plan provider call | 1 |
| evidence search | 3 |
| initial artifact provider call | 1 |
| structure/novelty repair | 合计 1 |
| specialized item repair | 1；只修失败 Item |
| provider calls 总计 | 4 |
| coding reference execution | 每题初次 1；repair 后重验 1 |
| starter leak execution | 每题初次最多 1；repair 后重验最多 1 |
| science generation verification | 每 Set 最多 3 |
| attempt 总 step | 12 |
| delivery attempt | 3；仅临时基础设施失败 |
| wall time | 保持 10 分钟 |

运行时只保留一套权威 step 计数；移除或停止使用与该合同冲突的旧配置。提高上限、允许多个 specialized item 或并行 Tool Call 需重新评审。

## 8. 错误分类与用户投影

保持既有 Job 状态。新增或细化稳定错误码，UI 按用户可行动类别展示：

| 用户类别 | 稳定错误示例 | retry |
|---|---|---|
| 材料/题型不适合 | `coding_item_not_supported_by_lesson`、`science_item_not_supported_by_lesson`、`insufficient_evidence` | 否；更换模式/完善课程 |
| provider artifact 无效 | `practice_artifact_schema_invalid`、`practice_citation_invalid`、`practice_formula_invalid`、`practice_duplicate` | 自动仅 repair；Job 不自动 retry |
| 编程 reference 无效 | `coding_contract_invalid`、`coding_reference_compile_failed`、`coding_reference_test_failed`、`coding_starter_invalid` | 自动仅单题 repair |
| 科学 reference 无效 | `scientific_answer_spec_invalid`、`scientific_reference_unverified` | 自动仅单题 repair |
| 基础设施 | `provider_unavailable`、`code_execution_unavailable`、`science_tool_unavailable`、`queue_unavailable` | 有限 retry |
| 预算 | `generation_budget_exceeded`、`grading_budget_exceeded` | 否 |
| 权威终止 | `practice_canceled`、`source_snapshot_stale` | 否；按当前状态重建 |

公开消息不返回 compiler stderr、provider 原文、题目正文、代码、tests、内部 URL 或路径。安全 trace 只记录阶段、语言、contract version、调用序号、状态、稳定 code、耗时、大小和计数。

## 9. 去重

- 历史范围：同一 Lesson Version 最近 50 题，最多 6,000 字符安全摘要；不含答案、rubric、reference 或 tests。
- exact：现有字母数字/大小写/标点规范化相同，硬拒绝。
- near duplicate：仅当 target、item type、task signature 相同，且规范化字符 3-gram Jaccard `>= 0.90` 时硬拒绝；阈值必须由中英文正反 fixture 证明不会把“同知识点不同角度”误杀。
- `0.75-0.90` 只作为一次 repair 的负例提示和观察指标，不硬拒绝。
- 不在 Slice 5 引入 Qdrant exercise collection、外部 embedding 或 LLM 判重；语义 embedding 作为后续候选，需独立成本与事实源评审。
- 为避免重复不得改变 Lesson target、扩大来源或生成不适合题型。

## 10. 兼容、数据和删除

- v1 Set/Item 不回填、不批量重新执行、不改变历史分数。
- grader 按 `answer_spec.harness_version` 分发；缺失版本按既有 v1 读取。
- 新 v2 Set 在 `generation_config` 固定 artifact version，coding Item 在私有 `answer_spec` 和公开 `interaction_spec` 固定同一 harness contract。
- 新增 `practice_jobs.artifact_contract_version` 非空列；migration 将既有行回填 `practice_artifact_v1`。新 Generation Job 显式写入 v2；遗留 v1 Generation Job 不恢复执行并稳定失败。已发布 v1 Set/Item 仍按自身版本读取和评分。
- 不新增表、其他列或 Job 状态；Set/Item 版本继续放入既有 JSON，删除、cancel、late-result 和 workspace scope 规则保持不变。
- 如果实现发现上述单列仍不足以建立约束或查询，必须先提交额外 migration 方案、旧数据处理和新 ADR 修订，重新人工 Gate。
- failed/ungradable grading 不产生 Mastery Signal、Weakness、Memory 或 Review Item；只有正式、可评分 Feedback 沿用既有投影。

## 11. Web 范围

- 不改 Reader 信息架构和统一代码工作台。
- Job 区显示安全阶段标签和可行动错误类别，不显示内部验证细节。
- coding 题显示 canonical contract version 的人类可读说明；旧 v1 题不要求用户迁移。
- scientific Feedback 明确区分“本地判定”“Wolfram 已验证”“未授权”“工具不可用”“结果不足”。
- 重试按钮只对权威可重试错误启用；结构/reference 失败引导重新生成，不伪装为基础设施重试。

## 12. 验收与 eval

### 12.1 自动化硬门禁

- 每个 validation stage 的正例、同类变体、无关反例和稳定错误码；
- Python/Java/C++ 真实 compiler/runtime matrix 全通过，不只检查 harness 字符串；
- reference 全测通过、starter 不泄露、代表性错误解不能全过；
- repair 只替换失败 Item，合法 Item/citation/target 不漂移；
- exact/near duplicate 中英文边界；
- scientific exact/numeric/symbolic、unit、tolerance、worked reasoning、未授权/不可用/结果不足；
- provider/MCP/queue retry 与结构错误不重试；预算、幂等、cancel/delete/lease/late result；
- 所有失败零半成品，所有非正式结果零学习事实副作用；
- v1 历史读取和 grading 回归，v2 version dispatcher；
- 日志、API、trace、eval report 不泄露私有字段。

### 12.2 真实 provider/Judge0 候选门槛

- 在至少两份真正含可执行目标的课节上，每种语言生成 5 次；每次只要求一种语言。
- 成功定义为 Set 已发布、reference 全测通过、刷新后可读并能提交一份正确和一份代表性错误答案。
- 每种语言至少 `4/5` 成功；任何语言不得为 0；失败必须全部归入稳定阶段，不允许 unknown/internal 泛化失败。
- 普通题在纯概念课节连续生成 5 次至少 `4/5` 成功，且不产生专业题。
- 科学题生成 5 次至少 `4/5` 成功，并覆盖 Wolfram 成功、不可用重试和结果不足 ungradable。

上述真实调用会消耗 provider/远程服务配额，执行前仍需按 Playbook 单独人工确认。若人工不接受该样本量或门槛，必须在 Gate 时明确替代值，不能由实现者临时降低。

### 12.3 Stage 4 最终人工 smoke

- 纯概念、算法/编程、数学/物理/化学三类真实课程；
- Python、Java、C++ 各生成、发布、正确/错误提交至少一题；
- 科学题一次 Wolfram 成功和一次不可用降级；
- 同课节连续生成无 exact/受控 near duplicate；
- UI 错误可行动，Network/trace 无私有内容；
- 完成此前延后的 Practice Set、Attempt、Course、Workspace 删除 Gate；
- API focused/full、migration、Web lint/build、Compose/readiness/Web 200、业务 smoke、OCR 全部真实完成。

## 13. 实现交接顺序

人工接受本 Spec 与 ADR 007 后，Codex 才生成 GLM 任务包。任务包按以下批次执行：

1. 先提交基线诊断报告，复现或排除事实盘点中的六项根因假设；
2. v2 domain artifact、canonical harness 与 compiler/runtime tests；
3. 分阶段 validator、单题 repair、预算和错误投影；
4. coding/scientific grading authority 与 learning side-effect tests；
5. 去重、Web 状态和兼容读取；
6. Codex 独立复验、经确认的真实 provider smoke、OCR、删除 Gate 和总结。

GLM 不得自行修改门槛、增加 migration、读取 provider key/用户原文、提交或 push。

## 14. 人工 Gate（已接受）

请逐项确认：

1. 是否接受 Slice 5 只做稳定化，不新增题型、MCP 或产品内多 Agent？
2. 是否接受 `practice_artifact_v2` / `solve_utf8_string_v2`，旧 v1 原样兼容且不迁移？
3. 是否接受每个 Set 最多一个 coding 或 scientific 专业题？
4. 是否接受第 7 节 repair/retry 分工与候选硬预算？
5. 是否接受只新增 `practice_jobs.artifact_contract_version`，不新增 Job 状态、表或其他列？
6. 是否接受科学验证缺失时不让 LLM 猜分，并按未授权、临时不可用、结果不足分别收敛？
7. 是否接受第 9 节的有界近重复策略，暂不引入 embedding/LLM 判重？
8. 是否接受每语言 5 次、至少 4 次端到端成功的真实 provider/Judge0 候选门槛？
9. 是否接受实现者必须先交基线诊断报告，再修改业务行为？
10. 是否接受自动化、真实 smoke、删除、OCR 与 Stage 4 最终 Gate 范围？

以上 10 项已于 2026-07-23 获人工接受。实现必须先交无业务改动的基线诊断报告；Codex 复核后才可继续主体修复。任何需要新增 Job 状态、额外 schema、更多 specialized item、提高预算或降低真实成功率门槛的变化都必须重新人工 Gate。

2026-07-23 追加人工 Gate：v1 generation 恢复被明确移出范围；v1 仅承担历史已发布 Set/Item 的读取与评分兼容。该决策替代第 10.1 节中“遗留 v1 Generation Job 沿用 snapshot 重试”的要求。

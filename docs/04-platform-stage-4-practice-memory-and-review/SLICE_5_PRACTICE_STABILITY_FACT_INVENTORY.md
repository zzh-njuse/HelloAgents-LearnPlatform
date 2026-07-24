# Stage 4 Slice 5 练习稳定性事实盘点

状态：事实输入；不是已接受的产品合同

日期：2026-07-23

## 1. 盘点结论

Slice 4 已证明代码执行 MCP、Judge0 三语言运行和 Wolfram MCP 可用，但这不能证明练习生成链路可靠。当前练习路径把题型适配、provider artifact、通用结构修复、编程 reference/starter 执行、科学验证、去重和最终持久化放在同一个 Generation Job 中；失败最终多被压缩为少量错误码，无法仅凭用户界面判断根因位于哪一阶段。

用户在 Slice 4 人工 smoke 中观察到 Java/C++ 生成成功率为 0。该比例是本 Slice 的首要调查输入，但本次文档阶段没有再次调用真实 provider 或 Judge0，因此不能把它写成已独立复现的统计结论，也不能先认定是 provider、harness、预算或执行后端中的某一方导致。

当前最需要修复的不是某个题干，而是建立可重复的分段诊断和验收方法：同一份 artifact 必须能回答“在哪一关失败、为什么可修或不可修、是否调用过外部工具、是否产生任何持久化副作用”。

## 2. 证据来源与边界

本盘点依据：

- 已接受的 Spec 001、Spec 004、ADR 001、ADR 002、ADR 006；
- Slice 4 完成总结、OCR 记录和 Slice 5 输入；
- 当前 `academic_companion/practice_agents.py`；
- 当前 `practice_type_adaptation.py`、`practice_generation.py`、`practice.py`、`practice_workers.py`；
- 当前 ORM、settings、Web 错误投影和 Slice 4 测试；
- focused 复验：在 `apps/api` 运行 `30 passed` 的 `test_slice4_codex_correction_013.py`。

未作为事实使用：

- 未读取或归档真实 prompt、上传原文、hidden tests、reference solution、用户代码或 provider 原始响应；
- 未在本轮调用真实 provider、Wolfram 或远程 Judge0；
- 未把 `.tmp/`、`artifacts/` 中未知运行产物当作产品合同或成功率证据。

## 3. 当前链路

```text
LessonVersion.practice_type_hints
  -> LessonLearningProfile
  -> determine_suitability
  -> PracticeAuthorRequest
  -> search-plan provider call
  -> 1-3 次 PracticeEvidenceSearch
  -> practice artifact provider call
  -> schema/citation/target/formula/exact-duplicate validation
  -> 最多一次整份 artifact repair
  -> coding reference/starter execution 或 science verification
  -> 最多一次 coding reference repair
  -> 最终 authority recheck
  -> Practice Set/Item/Citation 原子持久化
  -> Attempt
  -> deterministic coding/science evidence 或 LLM rubric grading
  -> Feedback
  -> Learning Event 投影
```

| 阶段 | 当前事实 | 当前主要缺口 |
|---|---|---|
| 课节画像 | `practice_type_hints` 来自 Lesson Writer 结构化 plan；旧课节或无 hints 时保守判为不支持 | 画像与 objective/evidence 的对应关系只在生成时使用，缺少独立可重放诊断用例 |
| 题型适配 | `require_*` 不适合时稳定失败，`auto` 跳过不支持题型 | capability、授权和材料适配共同影响结果，公开错误不能总是区分哪一项不满足 |
| artifact | Pydantic 同时校验普通、编程和科学题；整组必须包含普通题 | 单个专业题失败会使整组重写；错误最终常压成 `invalid_practice_artifact` |
| 编程合同 | 三语言均使用 `solve_utf8_string_v1`；reference、tests 和 harness 持久化前验证 | Java/C++ 的真实编译执行未成为 focused test 的硬门禁；部分测试只检查生成字符串包含标记 |
| repair | 通用结构修复一次；reference 失败后再修一次 | reference repair 只接收安全粗分类，不能区分 canonical contract、compile、runtime、test mismatch；修复会重交整组 artifact |
| 工具预算 | Set 授权默认 10 次；reference 和 starter 分别消耗调用，repair 后再次验证 | `practice_coding_max_ref_calls` 当前未进入运行时；6-step、20-attempt-step 和工具预算存在多套口径 |
| 科学题 | 生成前可验证规范答案；评分会把最终结果验证作为 LLM rubric 证据 | symbolic 验证未执行或结果不足时，当前路径仍可能继续让 LLM 产生数值评分 |
| 去重 | 同课节读取最多 50 个历史题干；规范化完全相同会拒绝 | “轻微改写但任务相同”只靠 prompt 避免，没有可解释的服务端近重复策略 |
| 错误投影 | Job/Attempt 有稳定 code/message；UI 对不适合题型有专门说明 | 用户仍难区分 artifact、citation、reference compile/test、科学验证、预算和基础设施阶段 |
| 自动化 | 覆盖 schema、幂等、取消、无持久化副作用和三语言 harness 形状 | 缺少三语言真实 compiler/runtime contract matrix、provider artifact 变体语料和分阶段成功率统计 |

## 4. 已验证的合同张力

### 4.1 编程调用预算并非单一口径

- Spec 004 写“每个 coding item 最多一次参考解验证任务”。
- 当前实现除了 reference 外，还会对非空 starter 执行一次完整测试；repair 后可再次执行 reference 和 starter。
- `practice_generation_max_tool_calls=10` 实际控制 Set 授权，而 `practice_coding_max_ref_calls=1` 没有被运行时读取。
- `practice_generation_max_steps=6` 仍被 eval 使用，运行时实际检查 `practice_generation_max_attempt_steps=20`。

因此，不能只提高重试次数；必须先统一 provider、search、execution 和 repair 的预算所有权。

### 4.2 Java/C++ focused tests 未证明真实 reference 闭环

现有测试证明：

- artifact 拒绝冲突的 `Main/main`；
- Java `public class Solution` 会在 harness 中规范化；
- Python/Java/C++ harness 都包含约定入口和 tolerance 文本；
- reference 失败时不会持久化 Practice Set。

现有测试没有证明：

- 代表性 Java/C++ provider artifact 经当前 wrapper 后能在真实 compiler/Judge0 通过；
- 转义、Unicode、换行、空输入、数值容差和边界输出在三语言完全一致；
- compiler error 能被归类并用于一次有界修复；
- repair 后的 reference、starter 和 tests 仍保持题意、引用和 hidden-test 私密性。

### 4.3 当前 repair 粒度会放大失败

通用 validation repair 和 coding reference repair 都要求 provider 返回完整 Practice Set。一个 Java/C++ 方法签名或转义错误可能导致已合法的普通题、citation 和其他题目被重新生成；这会增加新错误、重复和预算耗尽概率，也使前后成功率难以归因。

### 4.4 科学验证缺少“未调用、调用失败、结果不足”的评分硬分界

生成阶段无法验证远程科学答案时会拒绝 artifact。评分阶段对 exact/numeric 可本地判断；symbolic 路径如果没有授权或 observation 不足，`equivalent` 可能保持 `None`，随后仍进入 LLM grading。Slice 5 必须决定何时是可重试基础设施失败，何时是无分数 `ungradable`，不能让 LLM 填补缺失的确定性证据。

## 5. 待证实的根因假设

以下按优先级排列，但都不是已确认根因：

1. **canonical source 不一致**：provider、artifact validator、wrapper 和 Judge0 对 Java/C++ 的类、方法、include/import、可见性或转义接受集合不同。
2. **repair 信息不足**：安全分类过粗，provider 不知道是 compile、runtime 还是 test mismatch，重复产出同类错误。
3. **整组 repair 放大**：修一个 coding item 时重写完整 Set，引入新的 schema/citation/duplicate 失败。
4. **预算口径冲突**：starter、reference、repair 和多题共用 Set 工具预算，导致后置验证在成功前耗尽。
5. **测试代表性不足**：字符串形状测试通过，但没有覆盖真实 Java/C++ 编译、执行和边界输入。
6. **科学题事实不完整**：final answer 有值，但 worked solution、unit、equivalence 或验证 provenance 不完整，生成或评分只能泛化失败。

## 6. GLM 实现前必须完成的诊断矩阵

GLM 接手后必须先提交一份不改业务行为的基线报告，再开始修复：

| 维度 | 最小样本 | 必须记录的脱敏结果 |
|---|---:|---|
| 普通题 artifact | 正常、未知 citation、非法 rubric、重复题 | failure stage、stable code、是否 repair、零/有 Set |
| Python/Java/C++ reference | 每语言至少 3 个正例、3 个反例 | schema、compile、runtime、test、starter、预算各阶段结果 |
| 三语言边界 | 空输入、Unicode、换行、空白规范化、numeric tolerance | canonical harness version 与一致性结果 |
| 科学 artifact | exact、numeric、symbolic、单位、完整推导 | 本地/远程验证选择、结果充分性、评分是否允许 |
| 队列与权威 | duplicate、cancel、delete、lease lost、late result | 最终 Job/Attempt/Feedback/learning side effect |
| 历史去重 | exact、标点变体、同任务改写、同目标不同角度 | hard reject、repair hint 或允许及理由 |

诊断输出只能保存聚合计数、阶段、语言、contract version、稳定错误码、调用数、耗时和是否持久化。不得保存 source code、test case、题干、资料正文、用户答案、prompt、provider 原文、内部 URL 或绝对路径。

## 7. 当前不应采取的修复

- 不按 Java、C++、某本课程、某个题干或某条 compiler 文本添加特判答案；
- 不通过取消 reference validation、减少 hidden tests 或把失败题直接发布来提高成功率；
- 不把所有失败标成 provider unavailable 后自动重试；
- 不无限增加 provider/tool calls；
- 不把 Judge0、fixture 或某次 smoke 的偶然格式反向定义为产品合同；
- 不在没有 Spec/ADR Gate 时修改 schema、评分权威、队列状态或学习事实投影。

## 8. 对 Spec/ADR 的输入

Slice 5 需要一份新 Spec 和一份新 ADR。ADR 的必要性来自：

- 需要版本化 artifact/harness 合同并保持旧题可读、可评分；
- 需要重新定义结构 repair、reference repair、基础设施 retry 的所有权与预算；
- 需要把 deterministic score、科学验证和 LLM feedback 的权威分界写成跨 domain/API/worker/Web 合同；
- 需要决定是否新增 Job 状态或 migration。

本盘点建议不新增 Job 状态或新表。成功 Set/Item 可以利用现有 `generation_config` 与 `answer_spec.harness_version`，但失败或重试中的 Practice Job 当前没有可保存 artifact contract snapshot 的字段；为避免同一 Job 在部署升级后静默换版本，建议只增加一个 `practice_jobs.artifact_contract_version` 列。是否接受该最小 migration 由 ADR 007 人工 Gate 决定。

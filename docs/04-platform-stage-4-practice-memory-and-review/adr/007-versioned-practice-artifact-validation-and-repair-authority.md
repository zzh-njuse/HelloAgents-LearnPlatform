# ADR 007：版本化练习 Artifact、分阶段验证与有限修复权威

状态：已于 2026-07-23 通过人工 Gate

日期：2026-07-23

## 1. 决策摘要

Slice 5 建议采用版本化的 `practice_artifact_v2` 与 `solve_utf8_string_v2`，并把生成链路拆为固定验证阶段。Postgres 仍是 Set、Item、Attempt、Feedback 和 Job 的权威；provider artifact、MCP observation 和 repair draft 都不是事实，只有通过全部 Gate 的完整 Set 才能原子提交。

结构 repair、专业题 reference repair 和基础设施 delivery retry 是三种不同机制，拥有独立适用范围和硬预算。确定性编程分数、科学验证证据和 LLM 教学反馈保持分权：LLM 不改编程分数，也不在科学证据缺失时猜分。

不新增表或 Job 状态。新增一个 `practice_jobs.artifact_contract_version` 非空列，使失败、retry 和跨部署执行仍固定创建时版本；Set/Item 版本写入现有 JSON 事实。失败阶段写入细化稳定 error code 和安全 trace；旧 v1 题保持可读、可评分，不重跑。

## 2. 背景

ADR 002 建立了受控 Exercise Author、Answer Grader、独立 practice queue 和一次结构 repair。ADR 006 增加三语言 reference validation、科学验证和确定性评分。Slice 4 真实 smoke 证明工具边界成立，但 Java/C++ 生成持续失败，当前错误与预算无法可靠区分 provider artifact、canonical wrapper、reference tests 或基础设施。

继续在 prompt 中追加规则或提高重试次数会放大成本和不确定性，也无法保护旧题兼容。该问题跨越 domain artifact、worker、MCP、Postgres JSON、API/Web 错误和学习投影，因此需要独立 ADR。

## 3. 决策

### 3.1 权威与版本

- `PracticeSet.generation_config.artifact_contract_version` 保存 Set artifact 版本。
- coding Item 的私有 `answer_spec.harness_version` 与公开 `interaction_spec.contract` 必须一致。
- `PracticeJob.artifact_contract_version` 在创建时固定；worker、retry 和 reconciler 只能使用该 snapshot，不能读取部署当前默认后静默升级。
- 缺失版本按 v1 处理；v1 不回填、不重新验证、不改变历史 Feedback。
- v2 grader 只处理 v2；dispatcher 不允许用当前默认 harness 静默解释历史题。
- provider draft、repair draft、compiler output 和 Tool observation 不持久化为练习事实。

### 3.2 固定验证顺序

```text
profile/scope
  -> suitability/authorization/readiness
  -> evidence snapshot
  -> artifact schema/citation/target/formula
  -> novelty
  -> coding canonical/reference/starter 或 science answer verification
  -> final authority check
  -> atomic commit
```

阶段不可跳过或交换到持久化之后。任何阶段失败都不创建 Set/Item/Citation；取消、删除、lease lost 或来源变化使晚到结果失去提交权。

### 3.3 单题 repair，不重写合法 Set

- 初次 provider 返回完整 Set artifact。
- schema/citation/公式等跨 Set 错误最多允许一次整体 repair。
- novelty、coding 或 science reference 错误只允许修复失败 Item；请求固定原题 target、type、language、evidence keys 和 Set 数量。
- repair 后从该 Item 的 schema Gate 开始重跑全部后续验证。
- repair artifact 仍非法时 Job 失败；不得降级题型、减少题数、换目标或发布其余半组题。

### 3.4 三语言 canonical authority

- 产品拥有 wrapper、entrypoint、compiler/runtime 版本和 comparator；provider 只提交受限 solution source、tests 和题目 artifact。
- validator 可以做已列入版本合同的无语义规范化，不能自动修算法或 expected output。
- reference 必须通过全部 tests；学生分数由同一 immutable tests、comparator、weights 和 harness version 计算。
- compiler/runtime 的原始输出保持私有；repair 只接收稳定类别与有界位置摘要。
- starter 行为性泄露检查是独立预算项，不再计作 reference validation。

### 3.5 科学评分权威

- exact/numeric 本地规则有充分信息时由产品确定性判定。
- symbolic 等需要远程能力时，Wolfram observation 只是 bounded verification evidence。
- 未授权导致无法验证时可以正式提交 `ungradable`、无数值分；临时远程失败不提交 Feedback并有限 retry；成功调用但结果不足时提交 `ungradable`、无数值分及 limitation。
- LLM 按 rubric 评价推导过程，但不能把 `None/unknown` verification 转换成确定性结论。
- `ungradable`、failed 和 canceled 不产生学习投影。

### 3.6 repair、retry 与预算所有权

- artifact repair 只处理可由 provider 修复的结构内容；最多一次整体 repair。
- specialized repair 每 Set 最多一次，且每 Set 最多一个 specialized item。
- delivery retry 只处理 provider transport、queue、MCP 临时基础设施和 lease recovery；最多三次，沿用原 request/auth/schema/source snapshot。
- 材料不适合、结构/reference 仍非法、学生代码错误、schema drift、预算耗尽和取消不自动 retry。
- v2 使用一套权威 step counter；provider、search、Tool 和 repair 均在调用前计数。具体上限采用 Spec 005 第 7 节，配置名不得保留相互冲突的有效口径。

### 3.7 错误与可观测性

- Job 状态继续使用现有 `queued|running|retry_wait|queue_failed|cancel_requested|canceled|succeeded|failed`。
- error code 同时表达失败阶段和稳定原因；Web 再映射为材料、artifact、reference、科学验证、基础设施、预算或取消类别。
- 安全 trace 可以保存阶段、语言、contract version、ordinal、状态、计数、latency、size 和稳定 error code。
- 不保存 prompt、题干、课程正文、用户答案、source code、reference、tests、harness、compiler/provider/Tool 原文、URL、凭据或绝对路径。

### 3.8 去重权威

- 历史 Set/Item 仍以 Postgres 为事实源；不新增 Qdrant exercise index。
- exact normalized repeat 是确定性硬拒绝。
- v2 近重复只在相同 target/type/task signature 下，以版本化字符 n-gram 算法和阈值判定；算法输入为受限题干摘要，不含私有评分事实。
- 阈值和算法版本写入 `generation_config`，以便解释为什么拒绝；改变硬阈值需 eval 证据和 Spec 修订。

### 3.9 最小 migration 决策

现有 JSON 字段可以容纳成功 Set/Item 的版本，但 Practice Job 在成功前没有 generation JSON；只依赖部署默认会使旧 queued/retry Job 在升级后改变合同。因此新增：

- `practice_jobs.artifact_contract_version VARCHAR(...) NOT NULL`；
- migration 对既有行回填 `practice_artifact_v1` 后设为非空；
- API 创建新 Job 显式写当前批准版本；request hash 包含该版本；
- retry/reconciler 沿用原行版本；
- downgrade 只移除该加法列，不改 Set/Item/Attempt/Feedback 历史。

其他版本信息继续使用现有字段：

- Set artifact/novelty policy version；
- Item harness version 和 interaction contract；
- Job stable error；
- AgentRun/ToolCall 的安全阶段结果。

Slice 5 不新增其他列、表或状态。若实现需要按阶段查询聚合而现有 trace 无法可靠支持，应先证明缺口并修订本 ADR；不得用未 Gate 的 JSON 旁路或新表偷偷改变事实模型。

## 4. 影响

### 正向

- Java/C++ 失败可以定位到结构、compile、runtime、test 或 infra，而不是统一归入“生成失败”；
- repair 不再重写合法题，降低 citation/duplicate/预算连锁失败；
- 新旧 harness 行为可审计，历史题不会被新 wrapper 静默改变；
- retry 不再掩盖确定性内容错误；
- 科学工具缺失不会被 LLM 转换成伪分数。

### 代价

- domain artifact、worker 和 tests 需要双版本 dispatcher；
- 需要真实三语言 compiler/runtime CI 或受控集成测试环境；
- 单题 repair artifact 和阶段化错误增加实现复杂度；
- 真实成功率 Gate 会消耗 provider/Judge0/Wolfram 配额。

## 5. 未采用方案

### 方案 A：只加强 prompt

拒绝。prompt 不能证明 wrapper/compiler 一致性，也不能提供权威失败阶段和旧题兼容。

### 方案 B：reference 失败就整组重新生成

拒绝。会重写合法题与 citation，放大成本、重复和新结构错误。

### 方案 C：无限或大幅提高重试预算

拒绝。确定性 schema/compile/test 错误不会因 delivery retry 自动变正确，并会放大 provider 成本。

### 方案 D：取消 Java/C++ 或降低 hidden-test Gate

拒绝。Slice 4 已接受三语言能力；绕过 reference validation 会发布不可评分题。

### 方案 E：把 compiler stderr、hidden tests 或 provider 原文写入 Job

拒绝。它们包含私有实现与潜在敏感内容；诊断应使用稳定分类和本地受保护临时输出。

### 方案 F：新增 Job phase 状态和多张诊断表

暂不采用。现有状态机、error code 和 trace 足以表达 v2；先用最小数据改动验证价值。

### 方案 G：完全不做 migration

拒绝。失败或 retry 中的 Job 没有 Set `generation_config`，无法证明它在部署升级后仍按创建时 artifact contract 执行。

### 方案 H：用 LLM/embedding 判断所有语义重复

拒绝。会增加成本、不可解释性和新的事实源；Slice 5 先采用有界、版本化结构相似度。

## 6. 生效与回退

- 只有 Spec 005 与本 ADR 同时通过人工 Gate 后生效。
- v2 仅用于 Gate 后新建 Generation Job。v1 只保留已发布 Set/Item 的读取与评分兼容；migration 后遗留的 queued/running/retry v1 Generation Job 不恢复执行，以稳定的 `artifact_contract_unsupported` 失败，用户需要重新创建 v2 Job。
- 若 v2 出现回归，可停止创建 v2 Job；历史 v1/v2 Set 继续按各自版本读取和评分，不做数据回滚。
- 任何需要 schema、状态或专业题数量扩大的改变都回到人工 Gate。

## 7. 人工 Gate（已接受）

请逐项确认：

1. 是否接受 JSON 内版本化和 v1/v2 dispatcher，而不迁移历史题？
2. 是否接受固定验证顺序和“全部通过后原子提交”？
3. 是否接受整体 repair 最多一次、专业题单题 repair 最多一次？
4. 是否接受每 Set 最多一个 specialized item，以换取可控预算和可归因性？
5. 是否接受 starter leak check 与 reference validation 分开计数？
6. 是否接受 delivery retry 仅覆盖临时基础设施，最多三次？
7. 是否接受科学验证不足时无分数，LLM 不补确定性结论？
8. 是否接受稳定 error/trace 诊断而不持久化原始 compiler/provider/Tool 内容？
9. 是否接受版本化本地近重复算法，不新增 Qdrant/LLM 判重？
10. 是否接受只增加 Practice Job artifact version 列，不新增 Job 状态、表或其他列；发现额外必要性时重新 Gate？

以上 10 项已于 2026-07-23 获人工接受。只批准 `practice_jobs.artifact_contract_version` 这一项 schema 增量；实现若证明还需要其他列、表或状态，必须停止并重新人工 Gate。

2026-07-23 追加人工 Gate：开发环境旧 Practice Set 已经按产品删除合同清理，且不存在活动中的 v1 Generation Job。决策调整为“不恢复 v1 generation；仅保留历史已发布 v1 Set/Item 的读取与评分兼容”。该调整不新增 schema、状态或预算。

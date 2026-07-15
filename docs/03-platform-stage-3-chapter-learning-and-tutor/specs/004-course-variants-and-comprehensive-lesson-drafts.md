# Spec 004：独立课程对比与完整课节草稿

状态：已接受（2026-07-15 人工 Gate）

2026-07-15 语言选择补充 Gate：已接受。课程大纲和课节生成任务必须保存 `zh-CN` 或 `en`；默认 `zh-CN`。生成标题、目标、解释、示例和总结遵循所选语言，文件名、原文引用和必要专名允许保留原语言。

日期：2026-07-15

适用阶段：Platform Stage 3 Slice 2 人工 smoke 修正

## 1. 评审结论摘要

本规格修正两个已经由人工 smoke 证明影响可用性的行为：用户必须能在不删除现有课程的前提下创建另一门不同标题或学习目标的 Course，并在左侧列表切换比较；Lesson Writer 的目标从“生成带引用简介”提升为“在来源支持范围内尽可能完整、清晰地讲授当前课节”。

完整不等于无限运行。内容没有固定字数目标；系统使用可配置的高位技术护栏控制异常成本，并在覆盖未完成时显式失败，不能把截断内容标记为成功草稿。

本修正仍然只有 product orchestrator 控制的 Course Architect 和 Lesson Writer，不引入 Tutor 扩权、长期 Memory、Skill、MCP 或自主多 Agent。

## 2. Goal / Context / Constraints / Done when

| 项目 | 内容 |
|---|---|
| Goal | 用户可保留并对比多门独立 Course；每个课节草稿以知识覆盖而非固定长度为完成条件 |
| Context | 当前左侧一项对应一个 Course；同一 Course 的大纲重生成只产生 Course Version；当前 Lesson Writer 单次提交且共用 1,500 output token 上限 |
| Constraints | 保持 workspace/source snapshot/citation/Postgres 事实合同；不自动生成整门课程；不提交部分或截断草稿 |
| Done when | 新建课程入口、术语修正、自适应课节流水线、草稿重生成与版本审阅、专注内容页、预算/失败/trace、focused tests、Compose 与人工真实资料 smoke 全部通过 |

## 3. Course 与 Course Version 的用户行为

### 3.1 新建课程

- 课程左栏始终提供“新建课程”命令，不要求先删除或离开当前 Course。
- 点击后显示空白标题、学习目标、可选受众和来源选择表单。
- 每次提交创建新的 Course、独立来源快照和首个大纲 job；成功或运行中的 Course 都在左侧形成独立条目。
- 旧 Course、Course Version、Lesson Version 和 Tutor Session 不受影响。

### 3.2 同一课程的新大纲版本

- 当前 Course 内的“重新生成”改称“生成新大纲版本”。
- 该动作不创建左侧新条目，只为当前 Course 产生新的 draft Course Version。
- 用户要改变课程身份、标题或学习目标并保留对比结果时，应使用“新建课程”。

## 4. 完整课节的产品合同

Lesson Writer 的成功条件是：

1. 根据 Lesson 标题、目标、Course 结构和来源证据形成明确覆盖计划。
2. 对计划中适用于该课节的核心概念、原理/过程、例子、边界或误区以及总结进行有证据的讲解。
3. 不为了达到长度添加来源不支持的事实，也不把相同内容改写多次冒充完整。
4. 每个事实 block 继续引用当前 evidence ledger；证据不足的覆盖项必须明确标记 limitation，不能自由补写。
5. 覆盖复核通过后才原子创建 Lesson Version；任一阶段取消、失败、超时、引用无效或预算耗尽均不提交半成品。

本合同不规定统一字数、段落数或阅读时长。短而简单的课节可以较短；来源丰富、目标复杂的课节应自然生成更多分段。

### 4.1 草稿重生成与版本审阅

- 生成出一个 draft Lesson Version 后，同时显示“发布此版本”“重新生成草稿”和“专注审阅”，不能用“发布”替换掉生成入口。
- “重新生成草稿”创建新的 `lesson_draft` job；成功后创建新的 draft Lesson Version，不覆盖旧草稿或当前 published version。
- 管理界面默认选中版本号最大的草稿，并允许在该 Lesson 的历史草稿/已发布版本间切换比较。
- 发布动作明确作用于当前选中的 draft；发布其他版本或并发变化继续服从 expected current published version 的 409 合同。

### 4.2 专注内容页

- 草稿审阅和正式 Reader 都提供“专注审阅/专注阅读”入口，将课节正文扩展到接近整个 viewport，而不是继续挤在大纲或 Tutor 三栏中。
- 专注页保留稳定顶栏：返回、课程/课节标题、当前版本及主要动作；正文采用受控阅读宽度，长内容独立滚动。
- 草稿专注页显示当前 Lesson Version、引用、发布和重新生成；Reader 专注页显示已发布版本、引用、上一课/下一课。
- 返回按钮始终回到进入专注页前的课程管理或 Reader 状态；同时支持 `Escape`。不得因退出专注页丢失当前课程、课节、Tutor Session 或滚动外的业务状态。
- Tutor 默认不占用专注阅读正文宽度；保留返回常规 Reader 后继续问答的状态。本修正不新增悬浮 Tutor 或改变 Session 合同。

## 5. 受控生成流程

1. `PlanLessonCoverage`：产生最多 8 个有序覆盖单元及检索意图。
2. `CourseEvidenceSearch`：按覆盖单元在固定 source snapshot 内检索，构建去重 evidence ledger。
3. `WriteLessonUnit`：逐单元生成结构化 blocks，只接收该单元需要的证据。
4. `VerifyLessonCoverage`：检查遗漏、重复、无证据事实、结构和引用。
5. 只允许针对 verifier 指出的最多 2 个覆盖单元进行一次受控补写；不得扩大 source scope；补写后再次复核。
6. `SubmitLessonDraft`：组装、全量校验并在一个事务中持久化草稿和 citations。

这些名称描述 product-owned phase/tool；每个 phase 由同一个 Lesson Writer runtime 和 orchestrator 控制，不允许角色互相委派。

## 6. 建议预算

| 预算 | 默认值 | 行为 |
|---|---:|---|
| evidence ledger | 48,000 estimated tokens | 达到后停止加入低优先级证据；若核心覆盖仍缺失则失败 |
| 覆盖单元 | 最多 8 个 | 这是运行护栏，不是要求每课必须写满 8 节 |
| 单次生成输出 | 最多 8,000 tokens | 防止单个 unit 异常膨胀或 JSON 截断 |
| 正常整课节输出区间 | 8,000-16,000 tokens | 只用于观测/eval，不作为硬性通过条件 |
| 整课节累计输出 | 最多 32,000 tokens | 包含 coverage、unit、verify 和 repair 输出 |
| provider 调用 | 最多 12 次 | coverage 1 次、unit 最多 8 次、verify 1 次、补写最多 2 次 |
| attempt 墙钟 | 最多 20 分钟 | worker 必须 heartbeat；超时不提交部分草稿 |

预算必须按角色独立配置，不能继续复用 `PRODUCT_GENERATION_MAX_OUTPUT_TOKENS` 同时限制 Course Architect、Lesson Writer 和其他回答路径。每次调用及 attempt 累计 input/output token、调用次数和耗时写入现有 run/tool trace。

## 7. 失败行为

| 错误码 | 条件 | 用户行为 |
|---|---|---|
| `lesson_coverage_invalid` | coverage plan 无效或不能覆盖 Lesson objective | 可重试，不产生草稿 |
| `lesson_evidence_insufficient` | 核心覆盖项没有来源支持 | 显示资料不足，不自由补写 |
| `lesson_budget_exceeded` | evidence/output/call/wall-clock 护栏先耗尽 | 显示预算耗尽，不提交截断草稿 |
| `lesson_coverage_incomplete` | verifier/补写后仍存在核心缺口 | 显示覆盖未完成，可重试 |
| `invalid_agent_artifact` | 最终 schema 或 citation 无效 | 沿用现有失败合同 |

## 8. 验证与人工 smoke

- Web generation queue: starting another lesson does not replace the first task's visible state. The queue keeps task identity, status, attempt, cancel, and retry controls for recent jobs.
- Lesson unit structure failures receive at most one bounded repair call before the attempt fails; a canceled running job must converge to `canceled` and never persist a late provider result.

- API/DB：新 Course 与旧 Course 隔离；Lesson Version 只在最终事务产生；失败无半成品。
- Fake provider：简单课节、复杂多单元课节、证据不足、重复内容、未知 citation、输出截断、预算耗尽、取消和 lease 丢失。
- Eval：覆盖召回率、事实 citation 覆盖、重复率、limitation 正确性、input/output tokens、调用次数和延迟。
- Web：已有 Course 时新建另一门课程并切换；同 Course 新大纲版本不新增左侧条目；长课节正文与引用可读。
- Web：已有草稿仍可重新生成并保留版本；草稿/Reader 均可进入接近全屏的专注内容页并可靠返回。
- 人工 smoke：使用一份公开、结构较完整的真实资料生成一个内容丰富课节，逐项对照来源目录核对覆盖与引用。

## 9. 人工 Gate

1. 不同标题或学习目标的再次生成创建新 Course 并新增左侧条目；同一 Course 的重生成只创建 Course Version。
2. Lesson Writer 采用“覆盖规划 -> 检索 -> 分段撰写 -> 覆盖复核 -> 原子提交”，而不是单次长输出。
3. 内容没有固定长度要求；表中 48k evidence、32k 累计输出、12 次调用和 20 分钟是默认技术护栏。
4. 护栏耗尽或覆盖不完整时不产生可发布的半成品 Lesson Version。
5. 不借此引入自主多 Agent、Memory、Skill、MCP 或自动全课程生成。
6. 草稿与 Reader 都提供专注内容页；已有草稿继续允许生成新版本，并可在发布前切换比较。

以上 Gate 已于 2026-07-15 获人工接受。对于 Lesson Writer，本规格以自适应 12 次 provider 调用/8 次覆盖检索合同取代 Spec 001 的 4 step/3 次检索合同；Course Architect 的 6 step/5 次检索保持不变。

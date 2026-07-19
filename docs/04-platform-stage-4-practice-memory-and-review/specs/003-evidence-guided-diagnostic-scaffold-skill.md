# Spec 003：证据引导的诊断式支架教学 Skill

状态：已接受（2026-07-18 人工 Gate）

日期：2026-07-18

适用阶段：Platform Stage 4 Slice 3

## 1. Goal、Context、Constraints、Done when

| 项目 | 内容 |
|---|---|
| Goal | 将一种通用教学方法产品化，并让 Tutor 对课程依据和已授权学习状态进行综合、解释、排序和行动建议，而不是复述 Memory |
| Context | Stage 3 Tutor 已有版本/scope、RAG citation、队列、预算和 trace；Stage 4 Slice 1/2 已有 Practice、Mastery、Review、Memory 与 Lesson Completion |
| Constraints | Postgres 权威；只增加一种 Skill；不硬编码 smoke 问句；不改变 Mastery/Memory；不引入 MCP 或自主多 Agent |
| Done when | Skill/version 可选择可追溯，普通 Tutor 基线保留，结构/安全/质量 eval、API/Web、Compose、OCR 和人工 Chrome Gate 均有真实记录 |

## 2. 产品选择

首个 Skill 固定为 `evidence-guided-diagnostic-scaffold` v1，用户界面称“诊断式辅导”。它是参考 MathDial teacher move、自然语言 Tutor 策略实验和 ITS 研究形成的 research-informed candidate，只有通过本 Spec 的配对 eval 与人工 Gate 后，才能称为在本平台得到验证。

2026-07-19 的人工 smoke 发现 v1 把学习诊断强制塞进“课程定义 + 诊断”的固定回答骨架，并允许同一 Session 的异 scope/异课节历史进入上下文。修正按不可变版本规则发布为 v2：诊断/规划问题可以直接以 `learning_diagnosis`、`next_action` 或 `limitation` 回应；课节检索限定到当前课节版本引用的 chunk；历史限定到当前 scope，课节 scope 还必须匹配 `lesson_version_id`。v1 保留用于历史展示和原版本 retry，不原位改写。

方法顺序为：辨别任务、分离事实、校准学习判断、从有限教学动作中选择最小充分支架、给出一个下一步动作，并在适用时给自检问题。具体例子见 [Slice 3 Skill 运作示例](../SLICE_3_SKILL_EXAMPLE.md)。

Stage 3 普通 Tutor 只保留为离线配对 eval 基线和 Slice 3 前历史 Turn 的兼容路径，不作为用户可选模式，也不用于 Slice 3 新问题。

## 3. 用户价值

- 宽泛学习问题得到有依据的优先顺序和可执行动作，不得到 Memory 列表复述。
- “薄弱点”类问题区分 confirmed、provisional、evidence insufficient、completed reading 和 active Memory。
- 具体知识问题仍直接回答并引用课程资料，学习状态只改变解释重点。
- 用户不需要选择重复的“普通问答”模式；所有新问题自动获得诊断式辅导，并能在历史中看到实际采用的方法和版本。
- 等价措辞采用一致策略；无关问题或没有个性化依据时不强行套用 Memory。

## 4. 范围

### 4.1 范围内

- 一份不可变、版本化的教学 Skill 定义与结构化领域 adapter。
- Tutor Turn 级 Skill ID/version/content hash 快照。
- 结构化教学计划和回答验证；课程事实、学习状态和教学建议的边界。
- 现有 Memory/Completion 授权范围内的选择、最小化与 trace 计数。
- 当前 Skill/version 状态、历史回答版本标识和失败展示。
- 固定离线安全/合同 eval 与配对教学质量 eval。

### 4.2 明确不做

- 第二种教学 Skill、Skill 市场、用户上传 Skill 或运行任意 Skill 脚本。
- 修改 Mastery 公式、Weakness/Review/Memory 状态，或让 Tutor 写入这些事实。
- 从 Tutor 对话自动生成 Memory。
- MCP、代码/数学工具、日历、网页、文件工具、自主多 Agent。
- 认证、多租户、金额计费或通用质量 dashboard。
- 针对固定问句、关键词、fixture 或截图预期答案的专用分支。

## 5. 核心不变量

1. Skill 是教学方法，不是学习事实；其计划和输出不得写入 Mastery、Weakness、Review Item 或 Memory。
2. 课程事实必须来自当前 Turn 的 citation ledger；Memory、Completion 和 history 不是课程事实证据。
3. 学习状态只能来自当前 Workspace/Course/Lesson 范围内、用户已授权的产品投影；Skill 不扩大范围。
4. Completion 只表示完成阅读，不能表述为掌握；provisional 不能表述为 confirmed weakness。
5. 每个 Slice 3 新 Turn 在创建时固定当前发布 Skill 的 ID、version 和 content hash；客户端不能选择任意 Skill/version。
6. retry 沿用原 Skill snapshot，不随部署升级；晚到结果仍受 owner/lease/cancel/session/workspace 最终检查。
7. Skill 定义缺失、hash 不符或结构失败时，不静默降级为旧基础 Tutor。
8. Skill 不能通过关键词表决定用户意图；意图由受 schema 限制的计划产物产生，并以变体/反例 eval 约束。

## 6. 输入合同

诊断式 Skill 可以读取：

- Turn question、course/lesson scope、当前已发布 Lesson 标题/目标/正文结构。
- 最多 3 次、总计不超过 10,000 estimated tokens 的当前 Course Version 证据。
- 最近 8 个成功 Turn / 6,000 estimated tokens 的同 Session history，仅作连续性上下文。
- Workspace 已开启 Tutor Memory 使用时，当前精确 scope 内最多 5 条 active Memory，以及 mastery band、weakness certainty/status 的安全投影。
- 同一范围最多 10 条 Lesson Completion 摘要。

禁止输入：用户答案、rubric、feedback/evidence 正文、Memory revision 历史、其他 Workspace/Course、provider prompt、日志、绝对路径和内部连接信息。

与 Slice 2 相比，允许增加的是**安全的学习状态类型与分档**，不是原始评分或隐藏投影分数。API/Web 不公开的 `projection_score` 仍不得外发。

## 7. 结构化计划合同

第一 provider 调用返回：

- `intent`：`concept_explanation | learner_diagnosis | study_planning | self_check | other`；
- `queries`：1-3 个去重检索词；
- `learning_context_use`：`required | helpful | irrelevant | unavailable`；
- `teaching_moves`：从 `focus | probe | explain | example | next_action | check` 中选择 1-3 个去重动作。

服务端验证枚举、长度、数量和 scope。动作 taxonomy 参考 MathDial 的 Focus/Probing/Telling，但为本平台加入明确的 example、next action 和 check，并删除没有产品合同价值的 Generic 输出。非法计划不使用关键词推断，而是退化为 `other + 原问题检索 + explain`；该退化进入 trace 的安全 reason code。

## 8. 回答合同

诊断式回答最多包含以下有序 block：

1. `direct_answer`：先回应用户实际问题；课程事实需要 citation。
2. `learning_diagnosis`：仅在有学习状态依据且与问题相关时出现，必须标明 certainty；不得引用课程 citation 冒充学习状态来源。
3. `explanation` 或 `example`：提供最小充分支架，事实性内容必须有 citation。
4. `next_action`：一个具体、可执行且与当前 Course/Lesson/Review/Practice 能力相符的动作。
5. `check_question`：适用时给一个自检问题；不得把所有回答强制变成追问。
6. `limitation`：说明证据或学习状态不足以及需要补充什么。

服务端还必须验证：

- 至少有 `direct_answer` 或 `limitation`；
- 若 intent 为 diagnosis/planning 且有可用学习状态，至少有一个经过综合的 diagnosis/next_action，不能只复制输入条目；
- 课程事实 block 的 citation 全部属于当前 ledger；未知 citation 删除后导致事实 block 无引用时，该 block 无效；
- 不允许输出内部 Memory ID、evidence ID、intent reason、prompt 或 projection score；
- Memory 文本的长片段逐字重现不得作为“综合”通过，采用通用相似度/结构检查和 eval，而非固定内容黑名单。

## 9. 预算

| 项目 | v1 默认 |
|---|---:|
| Agent step | 5 |
| evidence search | 最多 3 次，每次最多 5 条 |
| evidence 总量 | 10,000 estimated tokens |
| history | 8 个成功 Turn / 6,000 estimated tokens |
| 学习状态 | 最多 5 条 Memory + 10 条 Completion，合计约 800 tokens |
| 最终输出 | 3,000 tokens |
| provider 调用 | 正常 2 次，最坏 3 次（计划 + 回答 + 一次结构修复） |

Skill 由服务端确定性加载，不额外消耗一个模型 Tool step。Stage 3 的 8,000/2,000 普通 Tutor 配置只作为配对 eval 基线和历史兼容参考，不作为新 Turn 的用户选项。token 缺失仍显示“未报告”，不以估算伪装 provider usage。

## 10. Skill 选择与版本

- Turn create 不接受 teaching mode 或 Skill 参数；服务端从 allowlist 自动解析当前发布 v1，忽略或拒绝客户端伪造的任意路径、prompt、version 或 hash。
- 数据库保存 `teaching_skill_id`、`teaching_skill_version`、`teaching_skill_hash`。Slice 3 前的历史 Turn 三者为空；Slice 3 新 Turn 三者必须全部非空。
- Skill 文件使用不可变版本目录；发布 v2 时保留 v1，以支持历史展示和原版本 retry。
- Skill prompt 正文不进入公开 API、普通 trace 或日志。公开 API 只返回 mode、稳定显示名和 version。

## 11. API 与 Web

- 复用现有 Tutor Session/Turn API，不新建聊天首页。
- Turn create 不增加用户选择字段；响应和 Session history 返回实际 Skill 显示信息。
- Web 按 `SLICE_3_FRONTEND_CONCEPT.md` 显示紧凑的当前 Skill/version，不增加 segmented control。
- 首次 Session 的外部处理确认已覆盖问题、课程片段、启用的 Memory/Completion；本 Slice不重复每 Turn 弹窗，但文案需包含“所选教学方法会处理这些内容”。
- 运行中控件和任务身份必须清楚；切换 mode 不替换或取消正在执行的 Turn。

## 12. 失败与降级

| 条件 | 行为 |
|---|---|
| 无课程证据且无学习状态 | 成功返回 limitation，不调用模型编造课程事实 |
| 有学习状态但无课程证据 | 可描述有来源的学习状态和下一步获取资料动作，不回答课程事实 |
| 无 Memory 授权/无匹配状态 | 基于课程证据教学，明确没有使用个性化状态 |
| 计划无效 | 通用 `other + 原问题` 检索，记录安全 reason code |
| Skill 缺失/hash 不符 | `teaching_skill_unavailable`，不静默改为旧基础 Tutor |
| 回答结构/citation 无效 | 最多修复一次；仍无效则 `invalid_agent_artifact` |
| provider/预算/取消/lease 失败 | 沿用现有稳定错误和最终权威检查 |
| 来源或课程版本变化 | 沿用 `source_snapshot_stale` / version authority |

## 13. Trace 与隐私

- AgentRun 继续归属 Tutor Turn；记录 role、attempt、step、status、token、latency 和错误码。
- 新增安全的 `TeachingSkillLoad`/`TeachingContextSelect` tool call 摘要：Skill ID/version/hash、输入类型计数、scope、结果数量和 reason code。
- 不记录问题、Memory 正文、Completion 标题、查询、evidence、prompt、provider 原始响应或最终答案正文。
- 用户删除 Session/Workspace 时，Turn 与关联 Skill trace 仍按既有删除图硬删除；Skill 静态定义不属于用户数据。
- 用户可以单独硬删除已结束的 Tutor Turn；问题、回答、引用、AgentRun 和 ToolCall 一并删除，后续历史不再读取。存在运行中 Turn 时拒绝单条删除，Session ordinal 不回退或重排。

## 14. Eval 与完成 Gate

### 14.1 硬门禁

- scope/workspace/version/citation、取消、retry、duplicate delivery、late result 和删除合同不回归。
- Completion 不被说成掌握，provisional 不被说成 confirmed，Memory 不替代课程 citation。
- prompt injection 覆盖 question、history、evidence 和用户编辑 Memory。
- 等价表达变体不得依赖固定关键词；无关反例不得强制个性化。
- 新 Skill Turn 的预算/snapshot/retry，以及历史基础 Turn 的只读与原路径 retry，均可重复验证。

### 14.2 配对教学质量 Gate

使用至少 16 个无敏感固定 case：4 类意图各 3 个变体，加 4 个不应个性化/证据不足反例。eval harness 使用相同 question、scope、evidence、history 和学习状态分别运行 Stage 3 baseline 与 Slice 3 Skill；baseline 不暴露为生产用户选项。

case 与 rubric 可以参考 MathDial 的 teacher move/过早告知权衡、MathTutorBench 的开放式教学评价和 SHAPE 的 helpfulness/pedagogy/safety 分离，但本仓库必须保存自己的固定、可解释 case，不直接把外部 benchmark 分数冒充产品效果。

人工盲评或固定 rubric 评估：问题回应度、证据忠实度、学习状态校准、综合而非复述、优先级、行动可执行性、解释充分度和不确定性。进入完成 Gate 的候选标准：

- 所有安全硬门禁通过；
- Slice 3 Skill 在至少 12/16 case 中不劣于 Stage 3 离线 baseline；
- 在 diagnosis/planning 的 6 个核心 case 中至少 4 个获得明确偏好；
- 不得以增加无依据断言、错误个性化或明显冗长换取分数；
- 至少一次经明确确认的真实 provider 配对观察和 Chrome 人工 smoke。

离线 fake provider 只证明编排与验证合同，不能冒充真实教学质量提升。

## 15. 实现顺序

1. 领域 Skill v1 定义、计划/回答 schema 与离线 case。
2. migration、Turn snapshot、API 投影和 retry 语义。
3. 受控 Skill 加载、上下文选择、prompt、验证和 trace。
4. 配对 eval runner/report。
5. Tutor UI 当前 Skill/version 与历史标识。
6. focused/full tests、migration、Web、Compose、真实 provider观察、Chrome smoke。
7. smoke 后按 Playbook 使用脱敏副本分块 OCR，修复后复验。

## 16. 人工 Gate

实现前需确认：

1. 首个 Skill 采用“证据引导的诊断式支架 v1”，Stage 3 普通 Tutor 只作为离线基线和历史兼容路径。
2. 所有 Slice 3 新 Turn 自动使用当前发布 Skill，不向用户提供普通问答切换。
3. Skill 仍使用 5 step/3 次检索，诊断式 evidence/output 上调到 10,000/3,000 tokens，正常 provider 调用仍为 2 次。
4. Skill 可以读取安全 mastery band/weakness certainty/status，但不能读取原始分数、答案、rubric、feedback 或 evidence 正文。
5. Skill/version/hash 固定在 Turn；显式 Skill 失败不静默降级。
6. 配对质量 Gate 使用 16 个 case 和上述最低标准，不用单个 smoke 问题证明完成。
7. 不引入 MCP、多 Skill、用户 Skill、自主多 Agent或新的长期学习事实。

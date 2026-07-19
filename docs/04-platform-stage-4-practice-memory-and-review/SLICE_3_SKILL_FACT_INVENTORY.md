# Stage 4 Slice 3 教学 Skill 与 Tutor 事实盘点

状态：完成；已作为 2026-07-18 人工接受的 Spec 003 / ADR 005 输入

日期：2026-07-18

## 1. 盘点目的

本盘点回答两个问题：当前仓库里的 Skill 到底是什么，以及为什么 Slice 2 的 Tutor 即使正确读取了 Memory，回答质量仍可能只是复述或上下限差异很大。

## 2. 当前可复用事实

### 2.1 Framework Skill

- `hello_agents.skills.SkillLoader` 扫描带 YAML frontmatter 的 `SKILL.md`，启动时只加载名称和描述，需要时再加载正文。
- `hello_agents.tools.builtin.SkillTool` 允许 Agent 按名称读取 Skill，并把正文作为 tool result 注入。
- Skill 可以带 references、examples、scripts 和 assets，但 framework 不提供产品级启用策略、历史版本锚点、数据库事实、权限、预算或效果评估。
- SkillLoader 的缓存和文件路径是运行时能力，不是 Postgres 产品事实，也不能单独证明某个历史 Tutor Turn 使用了哪一版教学方法。

### 2.2 Academic Companion 参考 Skill

`academic_companion/skills` 已有 `cs-interview`、`leetcode-patterns` 和 `paper-reading`。它们证明 Markdown 方法论可以被领域层维护，但主题偏向固定领域或任务，不适合作为通用学习平台的第一个产品教学 Skill，也不能反向定义产品 schema。

### 2.3 当前 Product Tutor

- Tutor Session 固定 Workspace、Course 和 Course Version；Turn 固定 course/lesson scope 与可选 Lesson Version。
- 每个 Turn 正常执行查询规划、最多 3 次课程证据检索、结构化回答和最多一次 JSON/citation 修复。
- 当前预算是 5 step、3 次检索、8,000 estimated evidence tokens、2,000 output tokens，history 为最近 8 个成功 Turn / 6,000 estimated tokens。
- 事实性 explanation/example 必须引用当前 Turn evidence ledger；资料不足可以稳定拒答。
- Slice 2 在 Workspace 明确启用后，按精确 Course/Lesson 范围最多读取 5 条 active Memory 和 10 条 Lesson Completion，并记录实际使用数量。
- Memory 只包含目标标题和用户可管理的展示文本；Completion 只说明用户完成过某一版本阅读。它们不含答案、rubric、feedback 或 evidence 正文。

## 3. 已观察到的质量缺口

当前 Tutor 的安全和数据边界成立，但教学合同过弱：

1. `search_prompt` 只规划检索词，没有明确用户当前需要解释、诊断、复习规划还是自我评估。
2. `answer_prompt` 只要求结构和引用，没有规定如何区分课程事实、学习状态、推断与下一步动作。
3. Memory 以一组摘要字符串注入。提示虽然要求“不要复述”，但没有可验证的综合、排序和行动输出合同。
4. Lesson Completion 与 Weakness/Memory 同处一段上下文，模型可能把“学过”误写成“掌握”，或把 active Memory 全部列出而不判断相关性。
5. 现有 block schema 能保证引用，却不能保证诊断校准、解释深度、行动可执行性或等价问法的一致策略。
6. 现有 eval 主要验证 scope、引用、拒答、历史隔离、取消和结构修复，未比较普通 Tutor 与明确教学方法的效果。

因此，Slice 3 不能继续靠追加零散 prompt 句子来关闭问题，也不能针对“我的薄弱点是什么”等人工 smoke 问句做输入到输出的专用分支。

## 4. 首个 Skill 候选比较

| 候选 | 优点 | 对当前缺口的限制 |
|---|---|---|
| 纯苏格拉底式追问 | 促进主动思考 | 宽泛规划或用户明确要求解释时可能回避直接帮助 |
| Worked example + 撤除支架 | 适合程序性知识 | 对概念诊断、课程规划和跨领域资料并不总适用 |
| 检索练习 | 与 Practice/Review 闭环自然 | 更像出题策略，不能覆盖 Tutor 的解释与规划问题 |
| 错因诊断 | 能利用 Weakness/Attempt | 容易把 Tutor 限缩为错题分析，不能覆盖一般知识问答 |
| **证据引导的诊断式支架** | 先区分事实和学习状态，再给适量解释、优先级、下一步与自检 | 需要新增结构化教学计划和输出合同，但不要求新增事实源 |

建议首个产品 Skill 为 **`evidence-guided-diagnostic-scaffold` v1（证据引导的诊断式支架）**。它是一种统一方法，不是多种 Skill 的打包：先判断学习任务和证据充分性，再选择最小充分支架，最终给出可核查解释与一个明确的下一步学习动作。

它当前应称为 **research-informed candidate Skill（有研究依据的候选 Skill）**，不能在本平台配对 eval 和人工 Gate 前称为“已验证有效”。经过研究支持的是教学策略方向与评估方法，不是本仓库尚未实现的具体 prompt、provider 或产品组合。

## 5. 研究与开源参考

### 5.1 MathDial：主要方法参考

- MathDial 提供约 2,861 段一对一数学辅导对话，以及 Focus、Probing、Telling、Generic 四类 teacher move 标注。
- 研究通过自动和人工交互评估关注“帮助学生继续推理”和“过早直接给出答案”的权衡。
- 本 Slice 只借鉴有限 teacher move、交互评估和反例设计，不复制数学内容、模拟学生或训练流程。
- 论文：<https://aclanthology.org/2023.findings-emnlp.372/>；官方仓库：<https://github.com/eth-nlped/mathdial>。

### 5.2 自然语言 Tutor 策略实验

- Chi、VanLehn、Litman 和 Jordan 的受控实验表明，在教学内容相同的情况下，不同 tutorial policy 仍可影响学习结果。
- 这支持把 Skill 定义为可版本化、可配对评估的教学决策策略，而不是更长的通用 prompt。
- 论文：<https://doi.org/10.3233/JAI-2011-014>。

### 5.3 ITS 与苏格拉底式基准

- VanLehn 的综述支持细粒度、适应性辅导的总体方向，但不能证明任一 LLM Skill 在本平台有效：<https://doi.org/10.1080/00461520.2011.611369>。
- Socratic Debugging Benchmark 显示苏格拉底追问可以被系统评估，同时通用模型仍低于人类专家，因此 v1 不采用“所有问题都反问”的纯苏格拉底策略：<https://aclanthology.org/2023.bea-1.57/>。
- MathTutorBench 和 SHAPE 可作为教学质量与安全评估维度参考，不作为本 Skill 已有效的证据：<https://github.com/eth-lre/mathtutorbench>、<https://aclanthology.org/2026.acl-long.529/>。

## 6. 建议方法步骤

1. **辨别任务**：从结构化 provider 计划中选择 `concept_explanation`、`learner_diagnosis`、`study_planning`、`self_check` 或 `other`；禁止由前端关键词表决定。
2. **分离事实**：课程内容以 RAG citation 为依据；Mastery/Weakness/Memory/Completion 只描述学习状态，不能替代课程事实。
3. **校准判断**：区分 confirmed weakness、provisional suggestion、insufficient mastery evidence、active Memory 和 completed reading，不把“完成阅读”说成“掌握”。
4. **选择教学动作**：从 `focus`、`probe`、`explain`、`example`、`next_action`、`check` 中选择 1-3 个动作。该有限 taxonomy 受 MathDial teacher move 启发，但按本平台的资料问答、Memory 和复习闭环调整。
5. **形成行动**：给一个与当前证据相符的下一步阅读、复习、练习或自检动作；资料不足时明确需要什么证据。
6. **自检收口**：在适用时给一个检查问题；用户要求直接答案或纯导航信息时不强制追问。

具体执行示例见 [Slice 3 Skill 运作示例](SLICE_3_SKILL_EXAMPLE.md)。

## 7. 不应直接复用的行为

- 不让模型自由决定是否加载任意 Skill；v1 只有产品 allowlist 中的一种教学 Skill。
- 不把 `SKILL.md`、模型教学计划或回答摘要写成 Mastery、Weakness 或 Memory。
- 不使用 `LearningAgent` 的本地 JSON Memory、UserModel 或 prototype session。
- 不增加网页、文件、MCP、代码执行、Todo 或自主多 Agent 工具。
- 不把 Skill 内容原样暴露给 Web，也不在普通 trace 中保存完整 prompt、Memory 正文或课程 evidence。

## 8. 实现影响盘点

预计涉及：

- `academic_companion`：新增不可变版本目录中的教学 Skill 定义、结构化计划/回答合同与 prompt adapter。
- Product API：Turn 选择校验、Skill/version/hash 快照、受控上下文装配、结构验证、trace 安全摘要与错误映射。
- Postgres migration：Tutor Turn 增加教学方式和 Skill 版本快照字段；不新建学习事实表。
- Web：Tutor 输入区增加清晰的教学方式选择，历史回答显示实际采用方式。
- Eval：增加普通 Tutor 与 Skill 的配对 case、等价问法和不应个性化的反例。

本 Slice 不需要修改 Slice 2 掌握度公式、Memory 状态机或删除语义的基本权威关系。

# Stage 4 Slice 5 输入：练习生成与评分链路稳定化

状态：计划外稳定性切片，等待事实盘点、Spec/ADR 分析与人工 Gate。

日期：2026-07-23

## 设立原因

Slice 4 已证明代码执行 MCP 和 Wolfram MCP 的真实可用性、安全边界与产品集成，但人工 smoke 暴露出练习生成链路仍不能稳定把课程材料转化为可发布、可执行、可评分的题目。Slice 5 不再扩展 MCP，而是把既有普通题、编程题和科学题收敛为可靠的端到端产品路径。

## 必须解决的问题

1. **生成合同稳定性**
   - 系统复核 `LessonLearningProfile -> suitability -> Practice artifact -> validation -> persistence` 全链路。
   - Java/C++ 题不能长期以结构校验、reference validation 或受控预算失败结束。
   - 科学题必须包含规范答案、完整解题过程、容差/单位/等价规则和可解释反馈所需事实，而不是只有数值。
   - 普通题也必须覆盖同一错误分类和 artifact 可靠性检查，不能只修某个语言或某次 smoke 输入。

2. **材料与题型适配**
   - 题型只能由课程规划阶段产生的结构化 objective/evidence hints 驱动，不得按课程名、关键词或测试材料硬编码。
   - `require_coding` / `require_science` 在材料不支持时应稳定说明不可生成；`auto` 应保守退化到合适题型。
   - 课程/课节规划应尽量避免把证据切得过薄，但不能通过虚构内容满足最低量。

3. **编程题 reference 与学生评分**
   - Python/Java/C++ reference solution 在持久化前必须通过固定 hidden tests。
   - Java/C++ harness、类名、输入输出协议、编译与运行错误必须使用同一 canonical 语言合同。
   - 学生提交只由 hidden test 权重确定分数；LLM 读取最小化的代码、测试摘要和课程依据生成讲解，不能修改确定性分数。
   - 前端应提供与代码实验室一致的编辑、stdin、运行结果、专注模式和最终交卷路径。

4. **科学题验证与反馈**
   - Wolfram 只验证明确的结构化 expression/结论；工具结果是评分证据，不自动成为学习事实。
   - 学生的推导过程需要进入受控评分上下文，使反馈能指出步骤错误；不得把“无法评判”作为所有异常输入的默认答案。
   - Wolfram 未被调用、调用失败或结果不足时，产品必须可见地区分降级原因，且不得伪造验证成功。

5. **去重与多次生成**
   - 新练习生成要读取同一 lesson version 的历史题目安全摘要，避免规范化完全重复，并研究受控的语义重复判定。
   - 去重不能泄露 hidden tests/reference answer，也不能导致“为避免重复而偏离课程材料”。

6. **错误分类与可观测性**
   - 面向用户至少区分：材料/题型不适合、provider artifact 无效、引用不足、reference 执行失败、科学验证失败、预算耗尽、队列/基础设施不可用和取消。
   - 日志和公开 API 只保留稳定错误码及脱敏摘要，不输出 prompt、原文、内部 URL、provider 配置或绝对路径。
   - 重试只能用于可重试故障；结构错误需在固定 repair 预算内结束，不能无限重试。

## 验收基线

- 用至少一份纯概念课程、一份算法/编程课程和一份数学/物理/化学课程完成真实浏览器 smoke。
- 对 Python、Java、C++ 分别生成、发布并提交至少一题；reference 和学生代码均通过真实 MCP/Judge0 链路。
- 科学题至少覆盖一次 Wolfram 成功调用和一次工具不可用降级。
- 同一课节连续生成多份练习，不出现完全相同题目；语义近似策略按 Spec 明确验收。
- 失败任务在 UI 中显示可行动的稳定原因，不泄露私有信息。
- 自动化覆盖 artifact 变体、反例、幂等、取消/删除/晚到结果、学习事实零副作用和三语言 harness。
- 完成 API focused/full tests、migration、Web lint/build、Compose、真实业务 smoke、OCR 与 Stage 4 延后删除 Gate。

## 明确不做

- 不新增第三项 MCP capability，不实现任意 MCP 市场或动态 Tool discovery。
- 不修改既有掌握度公式、Memory 投影或教学 Skill 产品目标。
- 不以某本测试 PDF、某个题干、某个关键词或固定答案增加专用分支。
- 不把 provider、fixture 或 Judge0 的偶然输出反向定义为产品合同。
- 不在未经 Spec/ADR Gate 的情况下重写整个 Practice schema 或引入自主多 Agent。

## Spec/ADR 前置问题

- Practice artifact 是否需要版本升级，以及旧 Set/Item 如何保持可读？
- repair/retry 的 step、检索和 Tool call 预算应如何分层，哪些失败可重试？
- 历史题目摘要如何进入生成上下文，语义去重采用何种可解释且有上限的机制？
- 编程与科学题的 reference、hidden tests、推导过程和 LLM 反馈分别由谁拥有权威？
- 是否需要新的稳定错误码、Job 状态或 migration？若需要，必须形成 ADR 并人工确认。

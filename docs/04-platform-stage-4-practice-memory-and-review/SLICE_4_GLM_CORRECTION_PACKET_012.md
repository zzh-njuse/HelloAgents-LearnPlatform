# Stage 4 Slice 4 GLM 修正任务包 012

日期：2026-07-21

## 1. 验收结论

Correction 011 仍未通过。新增代码包含无法由正式 provider artifact 产生的死链路，并且测试主要是 `inspect.getsource`、mock、导入或手工 ORM 构造，不是任务包要求的正式行为测试。

## 2. High：正式 artifact 合同没有扩展

### 2.1 Lesson 的结构化 hints/科学请求没有生产者

`course_generation.py` 用 `hasattr(plan, "practice_type_hints")`、`hasattr(verification, "practice_type_hints")` 和 `science_verification_requests`，但 `LessonCoveragePlan`、`LessonCoverageVerification`、prompt/schema 均没有这些字段。正式 provider 输出经过 Pydantic 后不可能产生这些值。因此：

- `LessonVersion.practice_type_hints` 永远不会由正式 Lesson Writer 写入；
- Lesson science verification loop 永远没有请求；
- Practice coding/science suitability 永远保守为 unsupported。

必须先扩展 `academic_companion/course_agents.py` 的不可歧义结构化合同、prompt、validation 和 repair，再由正式 Lesson Writer 产出并持久化。hints 必须绑定 objective key/evidence citation id，并声明可执行/可计算断言，不允许自由布尔值或关键词猜测。

### 2.2 Practice artifact 仍不支持 coding/scientific

`PracticeType` 仍只有 `single_choice|short_answer`，`PracticeItemArtifact` 没有 coding/scientific interaction、reference solution、public/hidden cases、language、science verification request。后续 `item.item_type == "coding"` 分支在正式生成 artifact 中不可达。

必须扩展 `academic_companion/practice_agents.py`、author prompt、validator、repair 合同，使正式 provider 能生成 general/coding/scientific artifact；服务端验证 objective/evidence 归属、题型结构和模式要求。

## 3. High：reference validation 顺序错误

当前实现先 `_commit_set()` 持久化并公开题目，随后才验证 coding reference；失败时仍保留 Set/Item，仅写 `_reference_validation_failed`。这违反“reference 全部通过才允许 artifact 入库”。

必须在任何 Set/Item 持久化前验证内存 artifact；任一 required coding reference 失败时进入一次受控 repair，仍失败则整个 Job 稳定失败且零 Set/Item。禁止留下不可评分的公开 coding item。

## 4. High：Tutor 不得维护第二套 MCP client

虽然 Tool 名已改为 `run_code`，`tutor_generation.py` 仍自行实现 initialize/list_tools/schema/call_tool。必须复用 `code_lab_execution.call_run_code_via_mcp()` 或抽取的唯一公共 client。canonical server identity、protocol、schema hash、错误分类只能有一套实现。

## 5. 必须补齐的产品行为

- coding grading 必须从正式提交路由进入 worker，不是只暴露一个旁路函数；队列、lease、owner、cancel/delete、retry、晚到结果全部适用。
- science generation/grading 和 Lesson verification 必须由正式 artifact 请求驱动，并通过逐 Job authorization/snapshot/预算。
- Practice UI 必须真正展示模式、语言、不可用原因和生成失败反馈；`auto` 支持可用题型，不强制。
- Code Lab 与 Tutor focus 必须保留编辑内容、语言、stdin/output、当前 Turn/Run 和滚动；不能只有全屏 CSS。
- Tool observation 对所有学习事实表保持零副作用。

## 6. 测试要求

删除或降级所有把 `inspect.getsource`、源码字符串、`hasattr`、importable、手工 ORM 插入称为“行为测试”的描述。静态检查可以保留但必须单列。

新增测试必须：

1. 通过正式 prompt/provider fake 返回扩展后的 Lesson/Practice JSON artifact。
2. 通过正式 `execute_generation`/worker 生成 coding/scientific/general Set。
3. 证明纯概念 material 在 `auto` 下零 coding/scientific，在 `require_*` 下零 Set 并稳定失败。
4. reference pass 才入库；fail->repair->fail 时零 Set/Item。
5. 通过正式 attempt API/worker 得到确定性 coding 分数，重复 delivery 不重复执行或写反馈。
6. Lesson science request 0..3、成功 provenance、失败 limitation、普通 Lesson 零调用。
7. Tutor fake MCP 断言唯一公共 client 调用 `run_code`，覆盖无授权、schema drift、失败降级和四重预算。
8. owner/lease/cancel/delete/source/scope 途中突变后零晚到 artifact。
9. 公开投影不含 reference/hidden tests/harness/private tool result。

运行 Docker Python 3.12 focused/full tests、真实 Postgres migration、offline eval、Web lint/build、Compose build/up/ready/Web 200。真实 VM/Wolfram/provider/Chrome/OCR 仍禁止。

## 7. 交回

报告必须给出扩展后的真实 artifact JSON 示例、正式入口测试名、DB 最终断言和 MCP 调用计数。不得再次把不可达分支或辅助函数称为完成。

完成后停止：不 commit、不 push、不 OCR、不宣布 Slice 4 完成。

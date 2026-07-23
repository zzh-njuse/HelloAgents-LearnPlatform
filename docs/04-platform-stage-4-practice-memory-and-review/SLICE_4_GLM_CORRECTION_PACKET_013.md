# Stage 4 Slice 4 GLM 修正任务包 013

日期：2026-07-21

## 1. Correction 012 验收失败

25 个测试虽通过，但其中关键测试仍使用 `inspect.getsource`/源码位置断言；文件头却声称无此类测试。正式端到端行为仍未被证明，并发现以下 High。

## 2. High：Lesson hints 没有真实归属校验

`PracticeTypeHint` 仍是可自由组合的布尔字段。当前 validator 不检查：

- `objective_key` 是否属于当前 plan unit/objective；
- `evidence_keys` 是否非空、是否来自该 Lesson 的检索 chunks；
- algorithmic 必须同时具有 executable evidence；science 必须同时具有 computable evidence；
- science request 的 `block_key/objective_key` 是否属于最终 artifact。

为 plan/verification 增加 model/service validation，并在 provider 首次输出无效时走既有一次 repair；repair 仍无效则稳定失败。不得信任 provider 自报布尔值。

## 3. High：Coding/Scientific 持久化合同错误

- `_answer_spec()` 把 `CodingTestCase` Pydantic 对象直接放入 JSON 列表，必须 `model_dump()`；否则真实 Postgres JSON 持久化失败。
- coding `interaction_spec` 从不存在的 `item.interaction_spec` 读取，最终总是 `None`。必须从 artifact 的 language/starter_code/public_examples 构造公开 interaction spec。
- scientific 分支落入 short-answer `_answer_spec`，丢失 `scientific_answer_spec`，`reference_answer` 为空；必须有独立私有 answer spec 与公开投影。
- public examples 与 hidden tests 必须严格拆分；hidden cases/reference/harness 不得进入公开 projection。

## 4. High：所谓 Python/Java/C++ harness 实际只有 Python

当前 reference/grading harness 始终拼接 Python：`import json`、`solution(...)`、Python `try`。Java/C++ 必然编译失败，且 artifact 没定义统一的 callable/stdio contract。

定义每种语言固定、可验证的交互合同。推荐统一 stdin/stdout 程序合同：单次执行 harness 输入全部 bounded cases，并由受信任 runner 判定输出；若采用 function contract，则分别实现 Python/Java/C++ 模板。禁止把任意 provider tests 拼进 shell/package/file/network。为三种语言分别做 reference pass/fail 和 attempt grading 行为测试。

## 5. High：失败没有受控 repair

注释声称 coding reference fail 后 repair，但实现直接抛错。按接受合同：首次 reference fail 后只允许一次 provider repair，repair artifact 必须重新经过 schema/citation/target/suitability/hidden projection/reference validation；仍失败则零 Set/Item。

## 6. High：Practice 正式 UI/提交路径不支持新题型

PracticePanel 仅新增生成模式选择。答题路径仍把除 single choice 外的所有题型当作普通文本：

- coding 没有 CodeWorkbench、language/starter/public examples/source_code 提交；
- scientific 没有公式渲染、单位/答案输入语义和相应 external grading ack；
- unanswered/pending/反馈展示没有按新题型处理。

完整接入 coding/scientific 的阅读、作答、交卷、轮询、反馈和遮挡答案状态。

## 7. High：队列权威与 science 链路未验证

对正式 generation/grading worker 增加 fake MCP 行为测试，覆盖 owner/lease/cancel/delete/source/scope 途中突变、retry、duplicate delivery、预算和最终提交。Science Tool 必须使用逐 Job authorization/snapshot；普通 Lesson/Practice 零调用；失败 limitation；Tool observation 对学习事实零副作用。

## 8. Web focus

Tutor 只有 CSS focus；Code Lab 没有 focus 按钮。按前端合同实现二者的 focus overlay/reducer，验证进入/退出/Escape 后保留 draft、language、stdin/output、selected Run/Turn 和滚动位置。

## 9. 必须替换的测试

以下不能计入行为测试：`inspect.getsource`、源码字符串/顺序、importable、schema contains、手工 ORM 构造。

新增测试必须从：fake provider JSON -> 正式 Pydantic -> 正式 service/worker -> fake MCP -> Postgres/SQLAlchemy 最终状态。明确断言 Set/Item/Attempt/Feedback、MCP 调用次数、公开 API 负面键和学习事实零变化。

至少运行：Docker Python 3.12 MCP/full API tests、真实 Postgres migration、offline eval、Web lint/build、Compose build/up/ready/Web 200。真实 VM/Wolfram/provider/Chrome/OCR 仍禁止。

## 10. 交回

报告逐项给出真实正式入口测试，不得把静态检查计作行为测试。完成后停止：不 commit、不 push、不 OCR、不宣布完成。

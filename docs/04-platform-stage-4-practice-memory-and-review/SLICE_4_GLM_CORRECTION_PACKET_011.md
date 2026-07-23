# Stage 4 Slice 4 GLM 修正任务包 011

日期：2026-07-21
前置：Correction 010 交回仍未完成已接受合同，并新增两个 High 回归。

## 1. 必须先修的 High

### 1.1 Tutor 调用了不存在的 Tool

产品 MCP server、shared contract 和 `code_lab_execution.py` 的固定 Tool 名均为 `run_code`，但 `tutor.py` authorization allowlist 与 `tutor_generation.py` 实际查找/调用的是 `execute_code`。这会使 Tutor 代码工具稳定失败。

统一复用现有 shared contract 与 `call_run_code_via_mcp()`；禁止另写第二套 handshake/client/schema。authorization snapshot 必须是 `run_code`。新增真实 fake MCP session 行为测试，断言成功调用 `run_code`，并覆盖无授权、schema drift、基础设施失败降级和预算耗尽。

### 1.2 题型适配违反禁止硬编码规则

`practice_generation.py` 用“算法/algorithm/编程/programming/数学/math/计算/comput”等关键词扫描 Lesson objective。这正是 AGENTS.md、Spec 和任务包明确禁止的按关键词/固定 smoke 内容判定。

删除全部关键词判定。题型适配必须来自结构化 provider artifact：objective/evidence 映射、可执行或可计算断言、预期 I/O/单位/符号关系及 evidence keys；服务端只验证结构和来源归属。必须有等价措辞、多语言、不应触发反例，证明不依赖关键词。

## 2. 不接受“缺真实后端/账号所以不能实现”

真实 VM 和 Wolfram 只影响最终环境 smoke，不阻止实现产品链路。仓库已有 fake execution backend/fake MCP session，Wolfram 也必须以 fake MCP server 验证。以下全部继续完成：

1. Practice coding reference validation。
2. Practice coding Attempt 确定性评分及教学反馈。
3. Practice science generation/grading。
4. Lesson Writer science verification、provenance、limitation。
5. Practice 创建模式/语言 UI。
6. Code Lab 与 Tutor 保留状态的专注模式。

## 3. 行为合同

- Practice provider artifact 明确声明 general/coding/scientific 类型及结构化 suitability evidence；服务端验证它引用当前 Lesson objective/evidence。
- `require_coding`/`require_science` 无合格 artifact 时稳定拒绝；`auto` 可退化为 general，不强行凑题。
- coding reference+harness 一次 `run_code` 全通过后才可持久化；hidden tests/reference/harness 永不公开。
- Attempt 的分数只由固定 case weight 计算，LLM 输出不能修改。
- Lesson/Practice science 调用必须有逐 Job authorization、snapshot、预算、authority 重检；失败写诚实 limitation，不伪造结果。
- Tool observation 不产生任何学习事实。
- UI 状态必须在 focus 进入/退出、Escape、scope 切换后符合已接受前端合同。

## 4. 测试与验证

测试必须直接调用正式 router/service/worker 和真实 fake MCP session，不得手工创建 ORM 行后宣称正式路径已验证。

至少覆盖：

- Tutor `run_code` 成功、无授权零调用、schema drift 零调用、失败 limitation、双 Tool 四重预算。
- Practice generation reference pass/fail、hidden projection、coding Attempt pass/compile/runtime/timeout、确定性加权分数、LLM 不可改分。
- Lesson/Practice science success/failure/不需要时零调用/晚到 authority 拦截。
- 结构化 suitability 的中文、英文、同义改写、纯概念反例，源码中不再存在关键词判定。
- Practice UI payload 与 focus reducer；Web lint/build。
- Docker Python 3.12 MCP tests 不得因 SDK 缺失 skip；API 全量 pytest；真实 Postgres 0020->0021->downgrade->upgrade；offline eval；Compose build/up/ready/Web 200。

真实 VM execution、真实 Wolfram、生成 provider、Chrome smoke 和 OCR 仍禁止，留给 Codex/人工 Gate。

## 5. 交回

逐项列出正式代码入口、行为测试名与真实断言、命令结果和剩余项。不得把 schema、辅助函数、手工 ORM 插入测试称为运行链路完成。

完成后停止：不 commit、不 push、不 OCR、不宣布 Slice 4 完成。

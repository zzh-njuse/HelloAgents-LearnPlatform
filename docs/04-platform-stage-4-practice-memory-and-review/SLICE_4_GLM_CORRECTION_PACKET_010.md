# Stage 4 Slice 4 GLM 修正任务包 010

日期：2026-07-21
依据：已人工接受的修订 Spec 004、ADR 006、`SLICE_4_FRONTEND_CONCEPT.md` 与 `SLICE_4_GLM_IMPLEMENTATION_PACKET_002.md`

## 1. 结论与范围

`SLICE_4_GLM_HANDOFF_REPORT_002.md` 不能通过 Codex 独立验收。报告开头声称 Batch A-G 全部完成，但第 7 节同时承认核心运行链路和 Web 集成未完成。现有 33 个新增测试只覆盖 ORM、公式校验和题型适配等局部单元，不证明 Lesson、Practice、Tutor 的端到端产品行为。

本修正包只补齐增量任务包 002 已接受的合同，不扩大到其他 MCP capability、任意 MCP 安装、产品内多 Agent 或真实远程调用。

## 2. 必须修复的 High

### 2.1 Batch C 并未接入 Practice 正式链路

代码事实：Practice router/service/generation/worker 没有消费 `item_type_mode`、`code_languages`、`interaction_spec`、Job Tool authorization 或 execution/science MCP。仅新增 `practice_type_adaptation.py` 和 schema 不算完成。

必须：

- 扩展正式创建 Practice Job API，并把模式、语言和逐 Job 授权纳入 request hash/idempotency。
- 在 generation worker 中从 Lesson objectives/evidence 产生结构化 suitability；`auto` 可退化为普通题，`require_coding`/`require_science` 不适用时稳定失败并给用户可理解原因，不生成伪题。
- coding reference solution + bounded harness 每题最多执行一次，全部通过才允许 artifact 入库；hidden tests/reference/harness 只写私有字段。
- coding Attempt 经 execution MCP 执行后按固定测试权重确定性评分；LLM 只能生成教学反馈，不能修改分数。
- science generation/grading 遵守本地优先、按需授权、预算、失败降级及最终 authority 重检。
- Tool observation 不直接写 mastery、Weakness、Memory、ReviewItem 或 Completion。

### 2.2 Batch D 并未接入 Lesson Writer

代码事实：只有 `CourseGenerationJob.science_tool_authorized` 字段；正式 course/lesson generation router、service 和 worker 未建立 authorization、plan、Wolfram verification、provenance 或最终 authority。

必须按任务包第 9 节接入正式 Lesson Writer，并确保：

- 只验证材料中确有必要验证的数学、物理、化学结论；普通概念课程零 Tool call。
- 每个 Lesson Job 最多 3 次，不能增加既有 provider call/step 上限。
- 失败时保留诚实 limitation，不伪造结论；外部结果不能冒充来源材料。
- cancel/delete/owner/lease/scope/source degradation 后的晚到结果不得提交。

### 2.3 Batch E 只保留了旧 science 链路，未实现 Skill v4 双 Tool runtime

代码事实：`tutor_generation.py` 仍只把 `science_tool_authorized` 传给 plan；没有传入/执行 `code_tool_authorized` 与 `plan.code_requests`。Web API payload 也没有正式发送 `code_tool_authorized`。

必须：

- Skill v4 Turn 同时支持独立 code/science 授权；未授权能力在 plan 前不可见，provider 越权请求必须在任何 MCP 调用前拒绝或清空。
- 严格执行总 MCP、code、science、decision-step 四重预算，retry 只能复制剩余预算和原 snapshot。
- code request 仅限 python/java/cpp、最长 12000 字符、无文件/网络/package/shell；调用结果以 bounded observation 进入 answer。
- science 与 code observation 分开，均不可带课程 citation id，不直接形成学习事实。
- 所有 Tool 失败均降级为诚实 limitation；禁止伪造运行/计算结果。

### 2.4 Batch A/F Web 核心组件未接入用户路径

代码事实：`RichLearningText.tsx` 和 `CodeWorkbench.tsx` 已创建但没有被 Lesson、Practice、Tutor、Code Lab 引用；Code Lab/Tutor 专注模式也未完成。组件存在不等于产品功能完成。

必须：

- `RichLearningText` 接入 Lesson 正文/草稿专注页、Practice stem/options/feedback、Tutor answer/history；只解析明确 math delimiter。
- `CodeWorkbench` 接入 Code Lab、coding Practice 和 Tutor 编码输入；不得继续用普通 textarea 作为主代码编辑器。
- Practice 创建界面提供 `auto/general_only/require_coding/require_science` 与适用语言选择，并展示“不适用”的稳定用户提示。
- Tutor 提供逐 Turn 的代码/科学工具授权，发送后清空且不继承。
- Code Lab 和 Tutor 增加可返回、保留草稿/语言/stdin/output/滚动状态的专注模式。
- 统一美化代码相关界面，保持现有紧凑工作台风格，不制作营销式页面。

## 3. Migration、删除与安全投影

- 在真实 Postgres 验证 0020->0021、downgrade->upgrade、历史 backfill、两个 owner 的恰一约束、partial unique、FK 与删除顺序。
- 检查所有 Practice Set/Attempt、Course/Lesson Job、Tutor Turn/Session、Workspace 删除路径，清除 authorization、hidden tests、source code 和私有 Tool result，并阻止晚到提交。
- 所有公开 API/SSE/log/readiness/feedback 均不得泄露 hidden input/expected/reference solution/harness、远端异常正文、内部 URL、key 或 provider 配置。

## 4. 必须新增的真实行为测试

不得只测试 dataclass/辅助函数或扫描源码字符串。至少补齐任务包 002 第 13 节全部矩阵，并直接调用正式 router/service/worker 与 fake MCP session：

1. 纯概念、算法、科学、混合材料的题型适配正例、等价改写和反例。
2. `auto` 退化、两个 `require_*` 稳定拒绝、request hash 冲突、重复 delivery。
3. reference 不通过不能发布；hidden tests 负面投影；确定性分数不受 LLM 输出影响。
4. 无授权零调用、双授权四重预算、schema drift、Tool error、retry 剩余预算。
5. owner/lease/cancel/delete/scope/source 途中突变矩阵，断言无晚到 artifact。
6. Lesson 普通内容零科学调用；必要科学内容验证成功/失败 limitation/provenance。
7. Tool observation 对学习事实表零副作用。
8. Web build/lint，并为可纯测状态 reducer 覆盖专注模式进入/退出、scope 切换、发送后授权清空。

## 5. 验证顺序

1. focused product behavior tests。
2. Docker Python 3.12 中运行所有 MCP 测试，不能保留因缺 SDK 导致的 skip。
3. API 全量 pytest。
4. 真实 Postgres migration upgrade/downgrade/upgrade。
5. Stage 3/4 offline eval。
6. Web lint/build。
7. `docker compose config`、相关镜像 build/up/ps、`/ready`、Web 200。
8. `git diff --check`。

不要调用真实 Wolfram、真实 VM execution backend、生成 provider 或 OCR；这些仍由 Codex/人工 Gate 控制。

## 6. 交回要求

报告必须区分“已实现并有行为验证”“仅建立 schema/组件”“未完成”。不得再把未挂载组件、未接入 runtime 或仅有辅助函数描述为 Batch 完成。

列出：实际修改文件、每条 High 的代码入口、行为测试名与断言、完整命令/结果、skip 及具体原因、真实 migration 结果、剩余风险、完整 `git status --short`。

完成后停止：不 commit、不 push、不 OCR、不宣布 Slice 4 完成。

# Stage 4 Slice 4 GLM 5.1 增量实现任务包 002

状态：可执行；修订 Spec 004 / ADR 006 / 前端概念已于 2026-07-21 通过人工 Gate

执行者：GLM 5.1

性质：在 2026-07-19 首版双 capability 实现候选上做增量实现；不是重写，不得执行已过期的 `SLICE_4_GLM_IMPLEMENTATION_PACKET.md`

## 1. Goal

完成以下统一学习闭环：

1. 课程草稿、Reader、Practice、Feedback 与 Tutor 可靠显示数学、物理和化学公式。
2. Lesson Writer 只在必要且获 Job 授权时调用 Wolfram，核验来源支持的计算或科学结论。
3. Practice 生成逻辑根据当前 Lesson objective/evidence 选择题型；支持 Python/Java/C++ 编程题和受控科学题，但绝不为满足选项强行凑题。
4. 编程 Attempt 通过 execution MCP 跑固定公开/隐藏测试并确定性评分；LLM 只能解释结果，不能改分。
5. 科学题可在生成或评分时使用 Wolfram；Tool observation 只是评分证据，不直接成为 Learning Event。
6. Tutor 在两个独立 Turn 授权内自主选择运行代码、调用 Wolfram或零调用，并根据真实结果讲解。
7. 实验室和 Practice 使用统一、美观的 CodeMirror 6 工作台；代码与 Tutor 都有保留状态的接近整页专注模式。

## 2. 仓库与真实运行环境

仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`

分支：`main`

宿主：Windows + PowerShell；Docker Desktop 使用 Linux containers。

当前已确认环境：

- 裸 `python` 指向 `C:\Python314\python.exe`，Python 3.14.0，**没有** pytest/FastAPI/MCP；不要用它跑项目测试。
- `apps/api/.venv-test/Scripts/python.exe` 是 Python 3.13.5，已有 FastAPI/pytest，但当前没有 `mcp`；它只能跑不依赖 MCP SDK 的测试，MCP skip 不能记为通过。
- API Dockerfile 的 `test` stage 使用 Python 3.12，安装 `requirements.txt + requirements-dev.txt`，包含 `mcp>=1.27,<2`，这是 MCP/API 行为测试的首选权威环境。
- Node `v24.14.0`，npm `11.9.0`；Web 有现成 `node_modules` 和 `package-lock.json`。
- Docker Engine/Compose 已启动；Compose `v2.40.2-desktop.1`。当前 `postgres`、`redis`、`qdrant`、`api`、`web`、`mcp-execution`、`code-lab-worker`、`capability-probe` 为 Up，API healthy，Web 为 `http://127.0.0.1:8080`。
- 当前 migration head 为 `0020_add_controlled_mcp_capabilities.py`；本任务只能新增 `0021`，不得修改 `0016`-`0020`。
- `.env` 存在，但禁止读取、输出或提交。provider、Wolfram 和内部 URL/key 不能出现在报告。
- execution MCP adapter 已运行，但独立 Ubuntu VM/Judge0/Piston 真实后端尚未配置；当前应稳定报告 `backend_not_configured`。不得启动 privileged backend 或声称真实三语言执行已通过。
- Wolfram 默认关闭且没有可用于本任务的已确认账号/额度；不得调用真实 Wolfram。
- 不调用真实 generation provider；所有生成、题型适配、评分和 Tutor 自动化使用 fake provider/fake MCP。
- `.tmp/`、`artifacts/`、pytest 临时目录均不是提交内容；现有 dirty files 是已知的 Slice 4 实现候选与文档，不得回滚。

如果本机 Docker 权限、网络或依赖下载失败，报告具体命令和错误。不得退回裸 Python 3.14、把 skip 当 pass，或手写一个简化编辑器/公式解析器冒充依赖。

## 3. 开始前必须完整读取

1. `AGENTS.md`
2. `docs/README.md`
3. 四份产品方向文档，尤其 `docs/AGENT_COLLABORATION_PLAYBOOK.md`
4. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
5. Stage 4 `README.md`、`SLICE_4_INPUTS.md`、`SLICE_4_MCP_FACT_INVENTORY.md`
6. `SLICE_4_FRONTEND_CONCEPT.md`
7. 修订后的 Spec 004 与 ADR 006
8. Slice 1 Spec 001 / ADR 001 / ADR 002，Slice 3 Spec 003 / ADR 005
9. Stage 3 Spec 004 与 ADR 006（Lesson Writer 覆盖、预算、原子提交）
10. `SLICE_4_EXECUTION_BACKEND_SPIKE.md`、首版任务包及 Correction 001-009/交回报告，只用于理解当前实现和已修问题；不得把旧禁止项覆盖新合同
11. migration 0016-0020、Practice/Course/Tutor service/worker/schema/tests、workspace deletion、MCP probe/adapter/shared contract、Web Course/Practice/Tutor/CodeLab/CSS/API

先运行并保存到交回报告：

```powershell
git status --short --branch
git diff --stat
docker compose ps
```

不要清理、stash、reset、checkout 或移动未知改动。

## 4. 当前实现事实：必须复用

- `apps/shared/mcp_execution_contract.py` 是 execution input/output schema hash 的唯一 canonical source。
- `apps/mcp_execution/` 已使用公开 MCP SDK Server/Streamable HTTP，并将基础设施错误与用户程序结果分开。
- `code_lab_execution.py` 已有固定 client handshake、schema hash、稳定 Tool error code、Run/Job authority；抽取公共调用时必须保持现有测试。
- `McpCapabilityStatus` + `capability_probe.py` 是 readiness TTL 权威；enabled/URL 非空不等于 ready。
- `TutorTurnToolAuthorization` 已保存 Turn capability snapshot；扩展 code authorization，不建立动态 MCP catalog。
- `PracticeJob` 已同时承载 `generate_set` / `grade_attempt`；Practice worker 已有 claim/lease/heartbeat/retry/cancel/duplicate-delivery/final-authority 模式。
- `PracticeItem.answer_spec` 已是隐藏评分材料；公开投影严格排除 reference/rubric/evidence 正文。
- `Tutor` 当前 Skill v3 已有 science request/observation 候选和 Correction 001-009 修复；新语义必须发布 v4，不原位修改 v1-v3。
- `CoursePanel` 已有 Reader/草稿 focus page；复用同一 overlay/返回/Escape/状态保留模式。
- 现有 `CodeLabPanel` 只是首版功能候选，UI 可重构，但不得删除 Run 历史、取消、删除、Tutor 显式摘要和错误状态。

## 5. 绝对禁止

- 不 commit、不 push、不跑 OCR、不调用真实 provider/Wolfram/execution backend，不读取 `.env`。
- 不开放任意 MCP URL、Registry、动态 Tool、resources/prompts/sampling/Apps/Tasks。
- 不准入 `WolframLanguageEvaluator`；只允许 WolframAlpha/WolframContext。
- 不让 Tool observation 直接创建 mastery、Weakness、Memory、Review Item、Completion 或 Learning Event。
- 不用 LLM 判断代码最终分数，不把 infrastructure failure 记为用户 0 分。
- 不为《人月神话》、管理、历史或纯概念课强行生成输出关键词、字符串拼接、背诵套代码壳等伪编程题。
- 不根据某个 smoke 问句、课程名、关键词或截图写专用分支。题型适配必须是结构化、内容无关合同，并有正例/反例测试。
- 不把 hidden tests、reference solution、rubric、用户代码/答案、课程原文、Tool 原文、prompt、key、URL、路径写进公开 API、SSE、日志或 safe trace。
- 不在 API/worker 内 `subprocess` 执行用户代码，不把 Judge0/Piston privileged Compose 合入主栈。
- 不修改旧 migration、旧 Skill 版本或 shared schema hash 来让测试“通过”。
- 不新增自主多 Agent、第三个 MCP、认证、计费、MCP 管理市场或分子结构渲染。
- 不使用普通 textarea 作为最终代码工作台，不自行发明公式/代码编辑核心库。

## 6. Batch A：依赖、统一富文本与公式渲染

先完成 Web 依赖和共享组件，不改业务数据库。

### 6.1 Web 依赖

使用 npm 正式加入并更新 `package-lock.json`：

- `react-markdown`
- `remark-math`
- `rehype-katex`
- `katex`
- `@uiw/react-codemirror`
- `@codemirror/lang-python`
- `@codemirror/lang-java`
- `@codemirror/lang-cpp`

不得加入 `rehype-raw`。不允许原始 HTML。KaTeX `trust=false`，不开放用户宏；加载 KaTeX CSS 与 `katex/contrib/mhchem`。

### 6.2 共享组件

新增小而明确的组件，例如：

- `RichLearningText.tsx`：受限 Markdown、inline/display math、`mhchem`、普通 code fence；渲染失败局部显示原表达式与“公式无法渲染”。
- `CodeWorkbench.tsx`：CodeMirror 6、language extension、行号、括号匹配、Tab 缩进、代码值/onChange、稳定高度、只读模式和无业务含义的编辑器 UI。

不要让组件读取 API、Workspace 或 Tool。业务组件拥有状态和命令。

将 `RichLearningText` 接入：LessonContent/草稿 focus、Practice stem/options/Feedback、Tutor answer/history。历史普通文本继续可读；只解析明确 math delimiter，不猜测货币符号。化学表达式必须写在 math delimiter 内，例如 `$\ce{H2O}$`，不要把裸 `\ce{...}` 当作 Markdown 扩展自行解析。

更新 Course/Practice/Tutor provider prompt 与 artifact validator：要求 `$...$`、`$$...$$`、`\ce{...}` 的受限语法；服务端至少验证 delimiter、长度和命令白名单。未知/危险命令、原始 HTML、超长表达式或不配对 delimiter 允许一次现有 artifact repair，仍失败则不提交。

Batch A 验证：Web lint/build；固定组件 fixture 覆盖公式、化学式、普通美元、恶意 HTML、未知命令、长公式和 code fence。项目没有现成 Web test runner时，不自行引入大型测试框架；把可纯测逻辑放小模块并以 build/lint + 后续 Chrome Gate验收。

## 7. Batch B：Migration 0021 与业务 schema

新增且只新增 `0021_add_integrated_learning_tools.py`。

### 7.1 Job 授权

新增 `job_tool_authorizations`（或语义等价表）：

- `id`, `workspace_id`, `capability_id`
- `course_generation_job_id` nullable
- `practice_job_id` nullable
- DB check：两个 owner **恰一非空**
- `(course_generation_job_id, capability_id)` 与 `(practice_job_id, capability_id)` 的 DB 级唯一约束/partial unique index
- `max_calls`, `used_calls`
- server/protocol/tool allowlist/schema hash snapshot
- `authorized_at`, `consumed_at`

不要复用 Tutor authorization 造成 owner 语义混乱。Tutor 继续用 `TutorTurnToolAuthorization`。

### 7.2 Practice 请求和题目

在 `PracticeJob` 增加不可变请求快照：

- `item_type_mode`: `auto | general_only | require_coding | require_science`
- `code_languages`: JSON array，成员仅 `python|java|cpp`，去重，最多 3

science/code authorization 不只保存 bool；进入 `job_tool_authorizations`。创建请求建议：

```json
{
  "item_count": 5,
  "difficulty": "standard",
  "output_language": "zh-CN",
  "item_type_mode": "auto",
  "code_languages": ["python", "java", "cpp"],
  "science_tool_authorized": false,
  "external_processing_ack": true
}
```

规则：

- `general_only` 零 MCP、只允许 single_choice/short_answer。
- `auto` 只在 capability ready、授权允许且材料适合时生成相应题型；不适合时普通题成功。
- `require_coding` 要求 code policy/readiness 和非空 languages；不适合时 Job 失败 `coding_item_not_supported_by_lesson`。
- `require_science` 要求 science authorization/readiness；不适合时 Job 失败 `science_item_not_supported_by_lesson`。
- required 类型无法满足时不得用普通题或减少题数伪装成功。

在 `PracticeItem` 增加 nullable `interaction_spec` JSON，公开只保存编程交互所需内容：language、starter_code、input/output description、constraints、1-3 public examples、runtime/time/output limit。普通题为 null。

私有 `answer_spec` 的 coding 结构固定：reference solution、3-20 hidden tests、comparator (`normalized_text|numeric_tolerance`)、显式 tolerance、test weights、harness version、target/evidence keys。公开 projection永不返回这些键。

`PracticeAttemptCreate` 增加 `source_code`（1..20000）；严格 exactly-one-of option_key/text/source_code。Attempt 继续保存不可变 JSON。

Feedback 增加安全的 coding execution summary：passed/total、compile/runtime/timeout/output-limited 分类、公开 case 结果和 bounded hints；不得返回 hidden input/expected/harness/reference solution。

### 7.3 Tutor 投影

Turn create 增加 `code_tool_authorized: bool=false`，保留 `science_tool_authorized`。二者都进入 idempotency request hash。

公开 Turn 增加：`code_tool_used`, `code_tool_call_count`, `science_tool_used`, `science_tool_call_count`，均由正式 ToolCall/authorization 投影，不相信客户端。

迁移测试必须覆盖 0020->0021、downgrade->upgrade、历史 backfill、owner check、unique、JSON 默认、Postgres FK/删除。SQLite ORM 表必须与 Postgres 合同一致。

## 8. Batch C：题型适配、Practice 生成与编程评分

### 8.1 领域 artifact

扩展 `academic_companion.practice_agents`，但不让领域层连接数据库/MCP：

- `PracticeSuitability`：每种候选题型 `supported|unsupported`、objective key、evidence keys、教学理由。
- generation artifact 可以是完整 Set，或 required 类型不适合的结构化 rejection。
- `coding` item schema 使用第 7 节固定 public/private 字段。
- scientific answer spec 保存规范化答案、单位/容差/等价规则和 verification request；不保存远程原文。

所有题仍由 provider 根据当前 Lesson objective、正文结构和 evidence 生成。MCP 只验证，不出题。

服务端验证：

- 每个 item target_key 属于 Lesson objective；每个 suitability/item evidence key 属于本 Job ledger。
- coding 必须检验有证据的算法、程序行为、数据处理、计算过程或可执行技能，并具有确定性断言。
- 禁止“打印某概念关键词”“把段落复制到字符串”“为纯概念事实套空程序”等通用伪题形态；不要使用课程名/固定关键词黑名单，使用结构要求和正反例 eval。
- scientific 必须有可计算/符号/单位/化学目标；纯概念不触发。

### 8.2 生成期 MCP 验证

把 execution/science MCP client、handshake、schema/error mapping 抽成 product-owned 公共服务；Code Lab、Practice、Lesson、Tutor 共用，不能复制四套协议实现。保留 `apps/shared` canonical execution schema。

- coding item：每题至多 1 次 MCP call，单次运行 reference solution + bounded harness；reference 必须通过全部 tests。
- science：每 Set Job 最多 3 次，仅验证答案/表达式/单位。
- 每次调用前和最终提交前执行 Job owner/lease/status/scope/source/capability/auth/schema authority。
- ToolCall 保存安全元数据；raw code/tests/result 只在 attempt 内存中使用，正式 answer_spec 保存必要私有测试，但普通 trace 不保存。
- Tool failure：required 模式明确失败；auto 模式可丢弃不可靠候选并用合法普通题重新提交，但最多一次现有 repair，不能无限生成。

Practice generation provider/search 上限保持 6/3。新增 attempt 总 step 护栏默认 20，用于准确计入 provider、search、code/science ToolCall 和 repair；不得把 ToolCall 漏出 `AgentRun.step_count`。代码验证最多 item_count 次，science 最多 3 次。

### 8.3 编程 Attempt

- 用户交卷创建 Attempt + 现有 `grade_attempt` Job；不得创建 CodeLabRun 冒充正式 Attempt。
- worker 使用 Item snapshot 组装 source + harness，在一次正式 execution 中运行公开/隐藏测试。
- 分数按通过 test weight 确定，verdict 使用现有四态；LLM 可读取**受限测试摘要**生成 explanation/improvement/reference，但不能修改 score/verdict。
- compile/runtime/timeout/output_limited 是用户程序结果；backend/schema/auth failure 是 Job failure/retry，不记 0 分。
- duplicate delivery、retry、cancel、lease lost、Set/Course/Workspace delete、late result 均零重复 Feedback/ToolCall/正式 Learning Event。
- 只有成功正式 Feedback 沿用现有 learning projection；Tool observation 自身零副作用。

### 8.4 科学题评分

- 能按固定 answer spec 本地判定时零 Wolfram。
- 只有 Item 标记且交卷已授权才可调用，每题最多 2 次。
- 将最小答案表达式/单位发给 Wolfram；不发送题目全文、课程正文、Memory 或其他答案。
- 无授权/失败且无法本地判定：`ungradable` 或稳定可重试失败；不猜分。
- Answer Grader 只能依据 rubric/evidence + bounded science observation 生成 Feedback。

## 9. Batch D：Lesson Writer 科学 verification

`LessonGenerationCreate` 增加 `science_tool_authorized: bool=false`，进入 idempotency hash。true 但 capability 不 ready 时创建前返回 `science_tool_unavailable`；false 时零 Wolfram。

在现有单角色 coverage->evidence->units->verify->submit 流程中增加受控 verification：

- coverage/verify artifact 可提出 0-3 个 `science_verification_requests`。
- 只允许验证来源 evidence 已支持的数值、方程、单位、物理关系或通用化学结论。
- 发送最小表达式，不发送课程片段；observation 与 citation ledger 分开。
- 通过验证的推导可在 block 保存 `external_verification` 安全 provenance；来源事实仍需要课程 citation。
- 失败时删除无法确认的推导、写 limitation 或使 Job 失败；不得补写来源外知识或显示“已验证”。
- 不增加既有 12 次 provider call 上限；science 最多 3 次，准确计入 AgentRun step/ToolCall/时间。

抽取公共 science MCP service，复用 Tutor 已修正的 allowlist、schema compare-only、稳定错误码和 prompt-injection 边界。不要让 Course worker读取任意 endpoint/Tool。

## 10. Batch E：Tutor Skill v4 与双 Tool 编排

新增不可变 `evidence-guided-diagnostic-scaffold/v4/`，保留 v1-v3。更新 allowlist 当前版本为 v4；历史 Turn/retry 按原 snapshot。

### 10.1 Plan

`TeachingPlan` 增加：

```json
"code_requests": [
  {"language":"python|java|cpp","source_code":"...","stdin":""}
],
"science_requests": []
```

- code <=2、science <=3、MCP 合计 <=3。
- 无对应授权时服务端在 provider plan 前不提供 capability，且 plan 返回请求也必须拒绝/清空为稳定 contract failure；测试断言零 MCP。
- plan invalid fallback 不创建任何 Tool request。
- 代码必须与当前 question/teaching move 直接相关，最长 12000 字符，无文件/网络/package/shell。

### 10.2 Execute/answer

顺序：plan -> RAG -> authorized code/science calls -> bounded observations -> answer -> one repair -> final authority。

- 新增 `code_observation` answer block；不能携带 course citation。
- 课程事实仍引用 evidence ledger；Tool provenance 单独显示。
- Tutor 可用剩余预算修正一次自己生成代码的 compile/runtime error，但总 code<=2、MCP<=3、step<=8。
- 工具失败但 evidence 足够：回答 + limitation；不足：明确无法验证。不得编造 stdout、测试通过或 Wolfram 结果。
- 普通概念问题在工具无增益时零调用；不能为了展示 MCP 调用。
- 现有用户选择 CodeLabRun 摘要继续可作为附加上下文，但不是自主 code call 的前置条件。
- retry 使用原 authorization/schema/Skill snapshot，不扩大剩余预算；删除 Turn 后后续 history 不能读取已删除问答或 Tool observation。

公开回答只显示“运行代码 N 次/科学工具 N 次”、稳定失败和经过综合的教学内容，不显示 raw Tool payload、endpoint/hash。

## 11. Batch F：Web 信息架构与美化

严格按已接受 `SLICE_4_FRONTEND_CONCEPT.md`，不要自由改变 Reader 导航。

### 11.1 代码实验室

- 用统一 `CodeWorkbench` 替换裸 textarea。
- 顶部：紧凑语言 segmented control、runtime/限制摘要、运行、取消、专注图标。
- 主区：单一工作台边界；桌面编辑器/输出合理分栏，窄屏上下堆叠。
- 输出 tabs：结果/stdout/stderr/编译；切 tab 不改变编辑器尺寸。
- 最近运行紧凑呈现，不挤压当前编辑器；状态紧邻运行按钮。
- 视觉保持现有产品绿色强调 + 中性编辑器表面，不做巨大卡片、嵌套卡片、渐变装饰或营销式布局。

### 11.2 Practice

- 生成表单使用明确 option set：自动选择、只要普通题、要求编程题、要求科学计算题；required 旁写明材料不适合会失败。
- 只有 capability ready 时启用相应选项；语言用 swatch/segmented control，不用难看的长下拉。
- coding item 直接在 Practice 主区使用 `CodeWorkbench`；不跳实验室。
- 正式交卷沿用整份提交；未答题提示按 1-based 页面题号。
- coding feedback 显示测试通过数、稳定错误类别、公开 case 和教学建议；绝不显示 hidden tests。

### 11.3 Tutor 与 focus

- 输入区两个默认关闭开关：自托管代码、外部 Wolfram；发送后清除，新 Turn 不继承。
- Tutor header 增加 lucide `Maximize2` 专注按钮；展开接近整页，保留 Session、历史、问题草稿、滚动、scope和当前授权，返回/Escape 恢复。
- 专注 Tutor 中问题输入区稳定最小高度 240px；回答 code fence 等宽、语法可读、复制、横向滚动。
- Code Lab/Practice 的 `Maximize2` 进入专注编码；复用 CoursePanel 现有 focus overlay，不另建营销页。返回后保留代码、语言、stdin、output tab、Run 选择和滚动。
- 所有按钮使用 lucide 图标与 tooltip；固定尺寸，长文案不撑破。

## 12. Batch G：Compose、配置与删除

- 不新增第三个 MCP server。
- 通用 course/tutor `worker` 与 `practice-worker` 需要固定 `MCP_EXECUTION_ADAPTER_URL` 并加入 `mcp-execution-net`，只为连接产品 adapter；不得给 adapter DB/Redis/Qdrant/storage/key。
- `practice-worker` 与通用 worker 获得 Wolfram enabled/URL/可选 secret；API/Web 仍只读 capability projection，不持有远程 secret。
- 为 Lesson/Practice/Tutor 增加独立可配置预算，默认必须与 Spec 一致；模型/客户端不能修改。
- 主 Compose 不加入 Judge0/Piston VM，不发布 mcp-execution host port，不挂载 Docker socket。
- `mcp-execution-net` 和 VM 访问规则不得让执行代码访问产品数据服务；真实负面验证留给后续人工 VM Gate。
- `/ready` 中 optional capability unavailable 不使全站 false ready，但公开明确状态。

扩展所有删除路径：Attempt/Set/Course/Lesson/Tutor Turn/Session/Workspace 删除 job authorization、私有 tests/code/result 关联并阻止晚到结果；删除 code lab 行为保持。删除失败必须保留可重试权威状态。

## 13. 必须新增的行为测试

测试必须调用产品函数/路由/worker/真实 fake MCP session；源码字符串检查只能单列为静态检查，不能冒充行为测试。

### 13.1 题型适配

- 纯管理概念、历史叙述、阅读理解：auto 零 coding/science；require_coding/science 返回稳定 unsupported，零无关 item/MCP。
- 真正算法/编程、数学、物理、化学 fixture：生成相应题型并映射 objective/evidence。
- 等价措辞变体与无关反例；不能依赖课程名或关键词。
- required 类型无法满足时不缩题、不换普通题、不伪成功。

### 13.2 Coding Practice

- Python/Java/C++ reference validation、正确解、错误解、部分 tests、compile/runtime/timeout/output limited。
- hidden tests/reference/harness 在 pre-submit API、错误、trace、日志、安全摘要中不存在。
- 确定性 comparator/weights；LLM 反馈不能改 score/verdict。
- idempotency、duplicate delivery、retry、lease/owner/cancel/delete/late result。
- infrastructure/tool error 不产生 0 分或 Learning Event。

### 13.3 Science Lesson/Practice

- 无授权零调用；authorized + necessary 调用；authorized + unnecessary 零调用。
- schema drift、unknown Tool、WolframLanguageEvaluator、timeout/429/invalid result、全部失败。
- Wolfram 不扩大 citation/source，不把 observation 直接写 LearningEvent/Memory/mastery。
- 本地可判定 scientific answer 零远程调用；不可判定未授权为 ungradable/失败而非猜分。

### 13.4 Tutor

- 四种授权组合；MCP 总3、code2、science3、step8。
- 代码/科学/两者/零工具的通用 plan；工具失败诚实 limitation。
- code correction 仍不突破预算；retry 原 snapshot；新 Turn/scope/session/workspace 不继承。
- Tool output prompt injection、历史污染、citation/provenance 分离、删除后 history 不回读。

### 13.5 Formula、安全投影与 migration

- 受限 TeX、化学式、恶意 HTML/宏/URL、长表达式、普通美元符号。
- API 所有 negative-key tests 更新：hidden tests/reference solution/Tool raw I/O/prompt/evidence 内文不泄露。
- 0020->0021 PostgreSQL migration、FK/unique/check、删除顺序、workspace isolation。
- AgentRun owner 恰一不回归；真实 step_count/ToolCall count/token missing 语义不回归。

保留并运行 Correction 002-009 与现有 Stage 3/4 eval；不得删除旧测试来获得绿色。

## 14. 验证命令与环境选择

### 14.1 Web

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform\apps\web
npm.cmd install
npm.cmd run lint
npm.cmd run build
```

只使用 `npm install` 更新 lock；不要删除 lock/node_modules 后盲目重建。网络下载失败则报告，不用手写替代品。

### 14.2 API/MCP 权威测试环境

不要用裸 `python`。首选 Docker test stage：

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
docker build --target test -t helloagents-api-slice4-test -f apps/api/Dockerfile .
docker run --rm helloagents-api-slice4-test python -m pytest -q <新增 focused tests>
docker run --rm helloagents-api-slice4-test python -m pytest -q
```

若测试需要真实 Postgres/Redis/Qdrant，使用 Compose 网络/服务并显式配置测试数据库，或在已启动 Compose 中运行测试容器；不得让测试写生产/用户 workspace。报告实际命令，不把 SQLite 结果冒充 Postgres migration。

`apps/api/.venv-test` 可快速跑不依赖 MCP 的 focused tests，但所有 `mcp` skip 必须在 Docker Python 3.12 中重跑。

### 14.3 完整验证

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
docker compose config
docker compose build api web worker practice-worker mcp-execution code-lab-worker capability-probe
docker compose up -d postgres redis qdrant mcp-execution api worker practice-worker code-lab-worker capability-probe web
docker compose ps

docker compose exec api alembic current
curl.exe -fsS http://127.0.0.1:8000/ready
curl.exe -I http://127.0.0.1:8080/

git diff --check
```

运行：Stage 3 offline eval、Stage 4 offline eval、现有 API full pytest、MCP focused tests、Web lint/build。真实 provider、真实 Wolfram、真实 VM execution、Chrome 人工 smoke 和 OCR **不运行**，交给 Codex/人工后续 Gate。

## 15. 必须停下并报告的条件

- 需要读取/输出 `.env`、key、内部 URL 或真实用户资料。
- 需要 privileged 主 Compose、Docker socket、产品 volume/network 才能执行代码。
- Wolfram Tool/schema 与固定 allowlist 不匹配。
- CodeMirror/KaTeX 依赖无法安装且只能手写弱替代。
- 0021 删除图、Job authorization owner 或 AgentRun owner 无法在 PostgreSQL 验证。
- required 题型只能通过硬编码课程/关键词或无关题满足。
- 必须修改已接受 Spec/ADR、旧 migration、旧 Skill 版本或学习事实规则才能继续。
- 发现未知 dirty change 与本任务文件冲突。

停止对应 Batch不等于停止所有可独立 Batch；在报告中精确说明完成和 blocker，不得降低合同。

## 16. 交回报告

新增 `SLICE_4_GLM_HANDOFF_REPORT_002.md`，逐项列出：

1. 修改/新增文件与完成的 Batch A-G。
2. migration 0021、API schema、authorization、题型适配、评分和删除图。
3. Lesson/Practice/Tutor 各自 plan->MCP->artifact 链路、预算和最终权威。
4. Formula/CodeMirror/专注模式的实际组件和状态保留。
5. Compose 网络与 secret 分配；明确 VM/Wolfram 仍未真实配置。
6. 每条验证命令、真实结果、passed/skipped 数；行为测试与静态检查分开。
7. 未运行项和具体原因。
8. 需要 Codex 独立复核的高风险点，至少包括 hidden tests 投影、题型适配反例、确定性评分、Tool observation 零学习副作用、lease/delete late result、双授权预算、公式 XSS/TeX 边界、Web focus 状态。
9. 完整 `git status --short`。

然后停止。不得 commit、push、OCR 或宣布 Slice 4 / Stage 4 完成。

## 17. 给 GLM 的接手 Prompt

```text
请接手 C:\Users\Admin\Desktop\HelloAgents-LearnPlatform 的 Platform Stage 4 Slice 4 增量实现。

严格执行：
docs/04-platform-stage-4-practice-memory-and-review/SLICE_4_GLM_IMPLEMENTATION_PACKET_002.md

先完整读取任务包第 3 节列出的指导文档、已接受的修订 Spec 004 / ADR 006 / 前端概念，以及当前代码和 Correction 001-009；然后运行 git status --short --branch、git diff --stat、docker compose ps。

这是在现有首版 MCP 实现候选上的增量开发，不得重写或回滚未知改动。特别注意任务包第 2 节的真实 Windows/Docker/Python 环境：不要使用裸 Python 3.14；MCP/API 权威测试使用 Dockerfile test stage 的 Python 3.12。不要读取或输出 .env/key/内部地址，不调用真实 provider、Wolfram 或 execution backend。

按 Batch A-G 顺序实施，每个 Batch 先跑 focused tests。题目必须来自 Lesson objective/evidence；纯概念课程不得强行生成编程/科学题。编程分数只能来自固定测试，Tool observation 不直接形成学习事实。Web 必须使用 KaTeX/mhchem、CodeMirror 6 和保留状态的专注编码/专注 Tutor，不得用普通 textarea 或简陋占位替代。

完成后按第 16 节写 SLICE_4_GLM_HANDOFF_REPORT_002.md 并停止。不要 commit、push、OCR，也不要宣布 Slice 4 完成。
```

# Spec 004：科学内容渲染与受控 MCP 教学闭环

状态：修订版已接受（2026-07-21 人工 Gate）

日期：2026-07-19；2026-07-21 扩展课程、练习与 Tutor 工具闭环

## 1. 修订背景

2026-07-19 接受的首版合同只交付独立代码实验室，以及 Tutor 按 Turn 使用 Wolfram。人工 smoke 证明这不足以形成学习闭环：代码执行没有进入编程练习和 Tutor 自主讲解，Wolfram 没有进入课程/练习的科学验证，正文也没有可靠的公式渲染合同。

本修订以原有双 capability、准入、隔离、Job、trace 和删除实现为基础，扩展到三个正式学习路径：

1. 课程正文可靠呈现数学、物理和化学公式，Lesson Writer 在必要时使用 Wolfram 核验计算或科学结论。
2. Practice 支持编程题，并允许数学、物理、化学题使用 Wolfram 生成或验证答案。
3. Tutor 在用户逐 Turn 授权后，自主选择运行代码、调用 Wolfram，或完全不使用工具，并结合真实结果讲解。

Wolfram 负责计算和验证，不负责浏览器排版。公式显示由产品拥有的受限 LaTeX 渲染合同完成。

## 2. 用户价值与完成标准

- 课程、题目、反馈和 Tutor 回答中的公式在桌面与窄视口均清晰可读，不向浏览器注入任意 HTML 或 TeX 宏。
- 学习者可以完成 Python、Java、C++ 编程题；分数由固定测试结果确定，不由模型猜测代码是否正确。
- 科学题的答案或关键推导可以通过经过审核的 Wolfram capability 复核，并明确区分课程来源、外部计算和模型讲解。
- Tutor 能在一个 Turn 内自行判断是否需要代码或科学工具，直接利用运行结果解释，而不是要求用户先去实验室手动运行。
- capability 不可用或调用失败时，系统诚实降级；没有结果就不声称已经运行、验证或计算。
- Tool observation 不直接创建或修改 mastery、Weakness、Memory、Review Item 或 Lesson Completion。

## 3. 范围

### 3.1 包含

- Reader、草稿审阅、Practice 题目/反馈和 Tutor 回答的数学与化学公式渲染。
- 受限 LaTeX inline/display math，以及 `mhchem` 的通用化学式/反应式。
- Lesson Writer 的可选 Wolfram verification phase。
- Practice `coding` item、公开示例、隐藏测试、代码提交、异步执行与确定性评分。
- 数学、物理、通用化学 Practice 的可选 Wolfram answer verification。
- Tutor Turn 的独立 `code_execution` / `science_computation` 授权和受控自主 Tool 选择。
- 原有独立代码实验室，作为调试、自由实验和运行历史入口。
- 固定 capability、schema/version snapshot、预算、幂等、队列、trace、取消、重试、删除与降级。

### 3.2 不包含

- 任意 MCP Registry、用户自定义 server URL、动态安装或未知 Tool discovery。
- JavaScript、Rust、Go、shell、第三方包安装、文件上传、持久工作目录或公网访问。
- WolframLanguageEvaluator、任意 Wolfram Language 执行、PubChem 或第三个 MCP capability。
- 分子二维/三维结构图、可交互公式编辑器、手写公式 OCR；这些不是“公式可靠显示”的组成部分。
- MCP result 直接更新学习事实，或用 Tool success 代替用户作答证据。
- 自主多 Agent、认证、多租户、计费或通用插件市场。

## 4. 公式内容与前端渲染合同

### 4.1 内容格式

- 结构化学习文本允许受限 Markdown，并使用 `$...$` 表示行内数学、`$$...$$` 表示块级数学；化学式或反应式使用数学定界符内的 `\ce{...}`，例如 `$\ce{H2O}$` 或 `$$\ce{2H2 + O2 -> 2H2O}$$`。
- 物理公式使用普通数学表达式；单位采用受限 `\mathrm{}` / 文本组合，不依赖未准入的任意 TeX package。
- provider prompt 必须要求只输出受支持的语法；artifact validator 在持久化前检查定界符配对、表达式长度、命令白名单和渲染可解析性。
- 无法修复的公式不能以原始反斜杠乱码作为成功内容提交；允许一次受控修复，仍失败则对应 artifact 失败。

### 4.2 渲染

- Web 使用固定版本 KaTeX 与 `mhchem` 扩展渲染；不依赖 Wolfram、浏览器 `eval`、远程脚本或运行时代码生成。
- 渲染前先按产品 Markdown 白名单清理；禁止原始 HTML、脚本、事件属性、任意 URL scheme、用户定义宏和可造成无限展开的 TeX。
- 渲染失败时显示可读的原始表达式和“公式无法渲染”，不得隐藏正文或让整个页面崩溃。
- 公式可横向滚动但不得挤压三栏布局；专注阅读、Practice、Tutor 历史和窄视口必须使用同一渲染组件。
- 历史纯文本内容继续可读；只有包含明确受支持定界符的内容才按公式解析，不对普通美元符号做猜测替换。

## 5. Lesson Writer 科学验证

### 5.1 何时允许调用

Lesson Writer 的 coverage plan 可以提出 `science_verification_requests`，仅用于：

- 数值计算、方程求解、单位换算或符号化简；
- 物理量关系和通用化学计算/反应式的核对；
- 来源中存在需要复核的明确科学结论。

不得用 Wolfram 扩大课程主题、替代来源检索、补写来源没有支持的知识，或把远程结果当作新的课程目录。

### 5.2 授权、预算和产物

- 创建或重生成 Lesson Draft 时，用户显式确认本次可把最小科学表达式发送给外部 Wolfram；授权只属于该 Job/attempt，retry 沿用原快照。
- 每个 Lesson Job 最多 3 次科学 Tool Call；计入 Lesson Writer attempt 的 tool/时间预算，但不占 CourseEvidenceSearch 次数。
- 发送内容只含必要表达式、单位和短问题，不发送课程原文、完整引用片段、Memory、prompt、内部 ID 或 provider 配置。
- Lesson 正式事实仍以课程来源 snapshot 为边界。Wolfram observation 只能验证来源支持的推导，并以 `external_verification` provenance 记录参与情况。
- 若验证失败，writer 可以删除无法确认的推导、明确 limitation，或使 Job 失败；不得伪造“已验证”。

## 6. Practice 编程题

### 6.1 题目合同

`PracticeItem.type` 增加 `coding`。每题固定：

- `language`：`python | java | cpp`；
- 题干、输入/输出说明、约束、初始代码（可空）、公开示例；
- 版本化评分规则、1-3 个公开示例和 3-20 个隐藏测试；
- 当前 Lesson Version 的 evidence ledger，说明题目所考知识点；
- 固定 runtime、时间、内存、输出上限和测试 harness version。

隐藏测试输入、期望输出、harness 和完整 rubric 在正式提交前不得进入公开 API。比较器只允许固定的规范化文本比较或带显式容差的数值比较；每个测试可有固定权重，分数按通过权重确定。生成 artifact 必须先经 schema、引用、重复 case、可执行性和参考解验证；参考解无法通过全部测试时整题无效。固定 eval 还必须证明代表性的错误解不能轻易通过全部测试。

### 6.2 生成

- 所有题目都由 Exercise Author 根据当前 Lesson 标题、学习目标、正文结构和固定来源 evidence 生成；编程题和科学题不是预制题库、与课程无关的工具演示，也不能只因 capability 可用就加入。
- 生成计划必须先对每种候选题型输出 `supported | unsupported`、对应 learning objective、evidence keys 和简短教学理由。服务端只允许 `supported` 题型进入写题阶段；模型自称“适合”但没有目标/evidence 映射时按不支持处理。
- 编程题必须能直接检验课程中有证据支持的算法、程序行为、数据处理、计算过程或可执行技能，并能形成确定性输入/输出或测试断言。不得把纯概念材料强行改写成字符串拼接、关键词输出、背诵题套代码壳等伪编程题。
- 科学题必须有材料支持的数学、物理或通用化学目标，并确实需要计算、符号、单位或反应式验证；纯概念题不因 Wolfram 可用而改造成计算题。
- 生成表单提供“自动选择合适题型”和“要求包含编程题”两种语义。自动模式下，编程/科学题不适合时静默改用普通单选或简答；用户明确要求编程题而当前课节不适合时，整个 Job 以 `coding_item_not_supported_by_lesson` 结束，说明材料和目标不足，不用无关编程题或普通题冒充成功。
- 用户明确要求科学计算题而材料不适合时使用 `science_item_not_supported_by_lesson`。同一 Job 不允许在用户要求的关键题型无法满足时缩减题数后伪装完整成功。
- 系统不得在 execution capability 未 ready 时接受“要求包含编程题”，也不得生成不可作答的编程题。
- Exercise Author 仍只在固定 Lesson Version 来源内出题。它可以请求受控 execution verification 验证参考解和测试，但不能自由运行任意探索代码。
- 每道编程题最多执行 1 个参考解和必要的 bounded test harness；生成期执行计入 Practice Generation Job 的调用和时间预算。
- 编程题与单选/简答可混合；题型分布必须在创建请求和任务身份中可见。

### 6.3 提交与评分

1. 用户交卷后，编程答案创建不可变 Attempt 和 Grading Job。
2. worker 在最终权威检查后，通过 execution MCP 在隔离后端执行公开与隐藏测试。
3. 测试通过比例按版本化、确定性评分规则产生 0-100 分和 verdict；编译错误、运行错误、超时和输出超限是可解释的用户程序结果。
4. LLM 可根据受限测试摘要生成教学反馈，但不能改变确定性分数或声称未执行的测试通过。
5. Feedback 只公开有教学价值的失败类别、公开 case 和脱敏提示；不得泄露可直接套答案的隐藏测试正文。
6. execution 基础设施失败时 Grading Job 失败或按临时错误策略重试，不产生 0 分或伪造 Feedback。

代码、stdin、测试输出和隐藏测试不得进入普通日志或安全运行摘要。删除 Attempt/Set/Course/Workspace 后按现有删除图清理代码、结果、关联 Run/Job/trace，并阻止晚到提交。

## 7. Practice 科学题生成与评分

- Exercise Author 可以在用户对该 Generation Job 授权后，调用 Wolfram 验证数值答案、等价表达式、单位或化学计算；每个 Set 最多 3 次。
- Wolfram 不负责决定教学目标或引用范围。题干、方法和所考概念仍须由 Lesson evidence 支持。
- answer spec 保存规范化答案、容差、单位/等价规则和 verification provenance；不保存不受控远程原文。
- 提交整份答卷时，若某题需要远程科学验证，UI 在一次交卷确认中说明必要的当前答案可能发送给 Wolfram；不对每题重复弹窗。
- Grading 最多对需要的科学答案调用 2 次 Wolfram；结果只是评分证据。产品评分服务/Answer Grader 依据固定 rubric、课程 evidence 和该 observation 形成 Feedback。
- 未授权、远程失败、schema 漂移或结果不确定时不得猜分。若本地确定性规则足够则不调用；否则该题进入 `ungradable` 或可重试失败状态。
- Tool observation 本身不产生 Learning Event；只有正式提交且通过产品评分合同的 Attempt/Feedback 才沿用既有 Learning Event 投影。

## 8. Tutor 自主工具使用

### 8.1 Turn 授权

Tutor 输入区提供两个默认关闭的 Turn 级授权：

- “允许本次运行代码（自托管）”；
- “允许本次使用 Wolfram 科学工具（外部服务）”。

用户可以单独开启或同时开启。发送后消费授权；retry 沿用原 Turn snapshot，新 Turn、scope、Session、Course 或 Workspace 切换不得继承。独立代码实验室选择运行摘要仍可作为显式上下文，但不再是 Tutor 使用代码执行的前置条件。

### 8.2 计划与预算

- 诊断式 Skill plan 可输出 0-2 个 `code_requests` 和 0-3 个 `science_requests`，但一个 Turn 的 MCP Tool Call 总数最多 3。
- 只有相应授权、Workspace policy、capability readiness 和固定 schema snapshot 全部有效时，请求才可执行。
- Tutor 总 decision step 上限由 5 提高到 8；evidence search 仍最多 3 次。Tool Call、提交和一次修复都计入 step，不能通过 retry 扩大预算。
- `run_code` 仍只允许 Python/Java/C++、无网络/文件/依赖安装；Tutor 生成的代码必须与当前问题直接相关，最多 12,000 字符。
- Tutor 可用一次剩余预算修正其生成代码的编译/运行错误，但必须在回答中区分首次失败和最终结果，不得隐藏失败。

### 8.3 回答

- Tool observation 以独立 `code_observation` / `science_observation` 进入 answer phase，不与课程 evidence citation ledger 混合。
- Tutor 必须先回答用户问题，再按需要解释运行输入、关键输出、计算含义、限制和与课程资料的关系。
- 课程事实仍需要课程 citation；代码/科学结论使用明确的 Tool provenance 标记，不能伪装成资料页码。
- 用户询问普通概念且工具不会增加价值时应零调用，不能为了展示 MCP 而调用。
- capability 不可用、调用超时、schema 漂移或全部调用失败时，回答必须包含 limitation。若课程 evidence 足够可继续回答，否则明确无法验证；不得编造 stdout、测试通过或 Wolfram 结果。

## 9. Capability、数据和权威

- 平台管理员只准入 `code_execution` 与 `science_computation` 两项 capability；用户不能配置任意 endpoint 或 Tool。
- `code_execution` 固定产品 MCP adapter、`run_code` schema、Python/Java/C++ 和独立执行后端。
- `science_computation` 固定 Wolfram Cloud MCP；远端可以公开额外 Tool，但产品可见、可授权和可调用集合严格固定为 `WolframAlpha` / `WolframContext`。`WolframLanguageEvaluator` 即使被远端公开也永远不得进入 plan、authorization 或 `call_tool`。
- Wolfram Cloud MCP 当前允许协商 `2025-03-26`；准入 hash 只覆盖获准的两个 Tool。额外 Tool 的存在不扩大 capability，未知或未获准 Tool 请求稳定拒绝。
- readiness 由 capability probe 写入带 TTL 的 Postgres projection；enabled 不等于 ready，schema/version 漂移立即阻止新调用。
- Postgres Job/Turn/Attempt 是权威；Redis 只投递，MCP session/Tasks 不成为产品事实。
- Tool 原始输入输出是所属业务对象的私有数据；公开 trace 只保存 capability、tool、schema/version hash、状态、耗时、大小、稳定错误码和调用序号。
- Tool observation 不能直接写 mastery、Weakness、Memory、Review Item 或 Completion，也不能绕过正式 Lesson/Practice/Tutor artifact validator。

## 10. 幂等、取消、重试和删除

- 所有创建命令继续使用 `(workspace_id, idempotency_key) + request_hash`；相同请求返回原资源，不同 payload 返回 409。
- worker 在每次 Tool Call 前及最终提交前重检 Workspace、业务 owner、Job/Turn/Attempt、lease、status、scope、capability readiness 和 schema snapshot。
- duplicate delivery 不重复调用或新增正式产物；取消为 best effort，晚到结果不得提交。
- 只有稳定的临时连接/服务错误可自动重试；用户代码错误、非法输入、schema drift、预算耗尽和确定性评分失败不自动重试。
- 删除 Lesson/Course、Practice Set/Attempt、Tutor Turn/Session 或 Workspace 时，先阻止新调用和晚到结果，再清理私有 Tool I/O、授权、Job、关联和 trace。
- 产品本地删除不宣称删除远程 Wolfram 可能保留的数据；UI/部署文档必须披露供应商边界。

## 11. 前端信息架构

- Reader 中间区域保留“正文 / 练习 / 实验室”。实验室用于自由实验和调试，不承担编程题交卷，也不是 Tutor 自主执行的前置步骤。
- Practice 的 `coding` item 在练习主区显示编辑器、运行约束、公开示例、提交状态和反馈；不跳转到实验室完成正式 Attempt。
- 练习生成的题型控件明确区分“自动选择合适题型”和“要求包含编程题/科学计算题”；后两者旁显示“材料不适合时将明确失败，不会强行凑题”。失败信息要给出缺少可执行/可计算学习目标，而不是 provider 原始错误。
- Tutor 授权开关紧邻输入区，以“自托管运行代码”和“发送最小内容到外部 Wolfram”区分数据边界；显示本 Turn 实际调用次数和失败/降级状态。
- Course/草稿、Practice、Tutor 统一使用公式渲染组件；公式块可滚动、可复制其可读文本，并在渲染失败时局部降级。
- 任务状态就近显示具体课程/课节/Practice/Turn 身份，不在页面底部形成无身份状态。
- 实验室和 Practice 编程题复用统一代码工作台：CodeMirror 6、语法高亮、行号、括号匹配、Tab 缩进、稳定工具栏和可切换的输出标签；不继续使用普通 textarea 冒充代码编辑器。
- 代码工作台与 Tutor 都提供右上角“专注”图标。专注编码接近整页展示编辑器与输出；专注 Tutor 接近整页展示历史、较大的问题输入区、授权和运行状态。返回或 `Escape` 后保留代码/问题草稿、选中语言、Session、历史滚动和授权状态。
- Tutor 的用户输入和回答代码块支持等宽字体、保留缩进、语法高亮、复制和横向滚动；右侧窄栏不再是长代码交互的唯一尺寸。

## 12. 预算默认值

| 路径 | 默认上限 |
| --- | ---: |
| Lesson Writer Wolfram | 每 Job 3 次；不增加 12 次 provider call 上限 |
| Practice Set science verification | 每 Set Job 3 次 |
| Coding item reference verification | 每题 1 次受控 execution（内部可运行 bounded tests） |
| Coding Attempt | 每 Attempt 1 次正式执行；基础设施重试不新增正式结果 |
| Science grading | 每题最多 2 次 Wolfram |
| Tutor | 8 step、3 次 evidence search、最多 3 次 MCP；code <= 2、science <= 3 |
| Tutor provider | 正常 plan + answer，最坏一次 artifact repair；工具调用不等于 provider 调用 |

预算耗尽以稳定错误或 limitation 收敛，不提交截断/半完成产物。token 缺失继续显示“未报告”，不得用估算伪装 provider usage。

## 13. Eval 与完成 Gate

### 13.1 公式

- inline/display 数学、分式、矩阵、上下标、物理单位和 `mhchem` 化学式/反应式。
- 非法定界符、超长表达式、未知命令、原始 HTML、脚本、恶意 URL、宏展开攻击和普通货币符号反例。
- 草稿、Reader、Practice、Feedback、Tutor、历史记录、专注页和窄视口一致渲染；单个公式失败不拖垮页面。

### 13.2 Lesson 与 Practice

- Lesson 无授权零 Wolfram 调用；授权后仅必要情况调用；验证失败不伪造结论或扩大来源。
- 纯概念课节在自动题型模式下不生成编程/科学计算题；明确要求不适合题型时返回稳定错误且零无关题目。固定 eval 至少包含《人月神话》一类管理概念反例、真正算法/编程正例和数学/物理/化学正例。
- 三语言编程题生成、参考解校验、公开/隐藏测试、编译/运行/超时/输出超限、部分得分和隐藏测试不泄露。
- scientific Practice 的本地可判定零调用、授权调用、等价表达式/容差/单位、远程失败 ungradable、Tool observation 不直接产生 Learning Event。
- Practice 幂等、duplicate delivery、lease/cancel/retry、删除和晚到结果。

### 13.3 Tutor

- 四种授权组合：都关闭、仅代码、仅科学、两者都开；未授权 capability 零调用。
- 需要工具时正确选择，不需要时零调用；总 3 次预算、code/science 子预算、schema drift 和 capability TTL。
- Tutor 依据真实 stdout/错误/科学结果讲解；工具失败显示 limitation，不伪造。
- prompt injection 覆盖 question、history、evidence、Tool result 和代码输出。

### 13.4 人工 smoke

- Chrome 中生成含数学/物理/化学公式的课节并在常规/专注 Reader 核对。
- 生成并完成 Python、Java、C++ 编程题，验证隐藏测试、部分得分、失败重试、删除和刷新恢复。
- 在纯概念课程中分别尝试自动模式和明确要求编程题：自动模式只生成合适的普通题，明确要求模式提示无法依据材料生成，且不出现伪编程题。
- 生成/完成需要科学验证的 Practice，并观察交卷时一次外发确认。
- Tutor 分别完成一次自主代码讲解、一次 Wolfram 计算、一次两者都不需要的普通问答和一次工具失败降级。
- Network/trace 不出现 hidden tests、代码、用户答案、课程原文、远程响应原文、prompt、凭据、内部 URL 或绝对路径。

Stage 4 最终仍需完整自动化回归、真实 Compose/readiness、可选真实 Wolfram Gate、隔离 VM execution smoke、Chrome 人工 Gate、分块 OCR 和脱敏运行摘要。

## 14. 合同演进与实现交接

- 本修订一经人工接受，覆盖原 Spec 004 中“代码不能由模型自主执行”“不自动判题”和“Wolfram 只用于 Tutor”的限制。
- Spec 001/ADR 002 的单选与普通简答合同继续有效；`coding` 和需要科学验证的题目按本 Spec/ADR 006 的增量合同执行。
- Stage 3 Lesson Writer 的来源、覆盖、citation 和原子提交合同继续有效；本 Spec 只增加受控 verification，不允许 Wolfram 代替 RAG。
- Stage 3/Slice 3 Tutor 的 Skill、history、Memory、citation 和结构化回答合同继续有效；本 Spec 只增加经授权的 Tool observations 与预算。
- 当前已实现的独立代码实验室、capability probe、MCP adapter、授权 snapshot 和 trace 作为基础保留，但不代表修订后的 Slice 4 已完成。
- 人工 Gate 通过后，Codex 需重新生成 GLM 修订实现任务包；不得让实现者自行决定题目 schema、评分、授权或渲染格式。

## 15. 人工 Gate（已接受）

接受本修订需确认：

1. 公式采用受限 Markdown + KaTeX + `mhchem`；Wolfram 只计算/验证，不承担渲染。
2. Lesson Writer 的科学验证按 Job 显式授权、最多 3 次，只验证来源支持的推导。
3. Practice 增加 Python/Java/C++ `coding` item；隐藏测试执行产生确定性分数，LLM 只能生成教学反馈。
4. 科学题可在生成或评分时使用 Wolfram；交卷时一次确认必要答案可能外发，失败时不猜分。
5. Tutor 提供代码与科学两个 Turn 级授权，可自主选择 0-3 次 MCP 调用；step 上限由 5 提高到 8。
6. 独立实验室继续保留，但不再是 Tutor 使用代码或编程题作答的前置入口。
7. Tool observation 不直接成为学习事实；正式 Lesson/Feedback/Tutor artifact 仍需各自 validator、来源和权威提交。
8. 题型选择只是受控偏好；所有题必须映射 Lesson objective/evidence。自动模式可省略不适合题型，明确要求但不适合时稳定失败，绝不强行凑编程/科学题。
9. 实验室、Practice 代码题使用统一 CodeMirror 6 工作台；代码与 Tutor 均提供保留状态的接近整页专注模式。
10. 接受新增 migration、Practice schema/worker、Tutor runtime、Lesson Writer phase、统一公式渲染和相应部署/测试成本。

以上 10 项已于 2026-07-21 获人工接受，可生成增量 GLM 实现任务包。题型适配、统一代码工作台和专注模式不得由实现者缩减为普通 textarea、强制凑题或独立实验室演示。

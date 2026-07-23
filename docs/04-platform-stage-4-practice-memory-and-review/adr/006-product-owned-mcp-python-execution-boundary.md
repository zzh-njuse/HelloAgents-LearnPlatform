# ADR 006：审核制 MCP 教学编排、执行与科学验证边界

状态：修订版已接受（2026-07-21 人工 Gate；2026-07-22 Wolfram Cloud MCP 兼容性修订人工接受）

日期：2026-07-19；2026-07-21 扩展决策

## 1. 决策背景

首版 ADR 只允许用户主动运行代码，Tutor 只能读取用户选择的运行摘要；Wolfram 只进入 Tutor Turn。人工 smoke 表明，这种边界验证了 MCP 连接，却没有把工具能力放进最有学习价值的课程生成、练习判题和 Tutor 讲解路径。

本次决定保留管理员审核、产品白名单、用户按业务动作授权和 Tool observation 非事实的安全模型，同时允许产品编排器在明确授权与预算内为 Lesson、Practice 和 Tutor 调用两项固定 capability。

## 2. 决策

### 2.1 固定 capability，不开放 MCP 市场

- `code_execution`：产品拥有的 Streamable HTTP MCP server，固定 `run_code` Tool，语言仅 Python、Java、C++，后接隔离 Ubuntu VM 中的成熟执行引擎。
- `science_computation`：管理员配置的 Wolfram Cloud MCP。远端可以公开额外 Tool，但产品可见、可授权和可调用集合严格固定为 `WolframAlpha` / `WolframContext`；`WolframLanguageEvaluator` 即使存在也永远不得进入 plan、authorization 或 `call_tool`。
- 管理员准入固定 server identity、协议、Tool 白名单、input/output schema hash、数据分类和 readiness TTL。
- 用户不能输入任意 URL，模型不能访问 Registry、安装 Tool、读取 server prompts/resources 或调用未知 Tool。

### 2.2 公式渲染不是 MCP capability

- 数学、物理和化学公式由 Web 的受限 Markdown + KaTeX + `mhchem` 渲染。
- 产品 artifact validator 拥有语法白名单、长度、定界符和可渲染性检查；不把 TeX 交给浏览器 `eval`，不加载远程脚本，不允许任意 HTML/宏。
- Wolfram 只提供计算或验证 observation。将 Wolfram 当公式排版服务会错误混合显示能力、远程授权和学习事实，因此明确拒绝。

### 2.3 产品编排器拥有 Tool 路由权

允许以下固定调用者：

| 调用者 | capability | 目的 | 用户授权 |
| --- | --- | --- | --- |
| Code Lab Run worker | code | 自由实验 | 点击“运行”即本 Run 授权 |
| Lesson Writer | science | 复核来源支持的科学推导 | 每 Lesson Job 明确授权 |
| Practice Generator | code/science | 校验参考解、测试或科学答案 | 每 Set Job 明确授权 |
| Practice Grader | code/science | 执行代码测试或核验科学答案 | 交卷时对所需外发一次确认；代码为自托管执行 |
| Tutor | code/science | 基于真实运行/计算结果讲解 | 两个独立 Turn 级授权 |

路由由受 schema 约束的 plan artifact 提议，产品服务根据 authorization snapshot、policy、readiness、白名单和剩余预算决定是否执行。模型不能直接持有 endpoint、凭据或通用 MCP client。

### 2.4 授权语义

- 代码实验室：用户点击运行，授权仅覆盖当前代码/stdin。
- Lesson/Practice generation：创建 Job 时保存 capability authorization snapshot；retry 沿用原 snapshot，不随当前开关扩大。
- Practice grading：若 Set 声明可能需要 Wolfram，交卷确认一次；不得逐题弹窗。未授权且无法本地判定时进入 `ungradable`/稳定失败，不偷偷外发。
- Tutor：代码与科学分别默认关闭；发送后消费。retry 沿用原 Turn snapshot，新 Turn 和 scope/session/course/workspace 切换不继承。
- 管理员 disable、readiness 过期或 schema drift 会阻止新调用，即使历史 authorization 为 true。

### 2.5 Agent 自主代码执行的受限接受

撤销首版“任何 Agent 不得运行代码”的绝对限制，改为：

- 只有 Tutor、Practice Generator 和正式 Practice Grader 可以在各自固定合同内请求 `run_code`。
- Tutor 每 Turn `code_requests <= 2`，所有 MCP 调用合计 `<= 3`；只能运行与当前问题直接相关、长度受限的 Python/Java/C++ 代码。
- Practice Generator 只执行结构化参考解与固定 harness；Practice Grader 只执行用户答案与该 Item 的不可变 tests。
- Tool 仍无 shell、依赖安装、文件上传、产品挂载、产品网络或公网；Agent 无权修改 runtime/resource policy。
- 编译/运行错误是 observation，不是基础设施失败。基础设施失败不得伪装成用户代码错误、0 分或成功结果。

### 2.6 题型适配权威

- capability readiness 只表示工具可用，不表示当前课节适合产生对应题型。
- Exercise Author 的结构化计划负责提出题型与教学理由，产品 validator 负责强制 Lesson objective/evidence 映射；二者共同构成题型适配 Gate。
- 用户的题型选择分为“自动允许”和“明确要求”。自动允许不形成数量承诺；明确要求在不适合时稳定失败，不允许 provider 用无关任务、代码壳或降级题型满足表面数量。
- 纯概念、管理、历史或阅读理解材料若没有可执行技能，不生成编程题。没有可计算科学目标的材料不生成 Wolfram 科学题。
- 题型不适合是业务结果，不是 provider/infrastructure failure，不自动重试，也不通过换模型绕过。

### 2.7 科学工具使用

- Lesson Writer 和 Practice Generator 只能验证已有目标/answer spec，不能用 Wolfram 扩大课程来源或自行增加教学主题。
- Tutor 可以在当前问题确有计算价值时自主选择 Wolfram；普通概念问答应零调用。
- Practice Grader 优先使用本地确定性规则；只有等价表达式、单位、数值或化学计算确需远程能力时调用。
- Wolfram 输入始终最小化，不发送课程原文、完整 citation、Memory、history、代码、prompt、内部 ID/URL、路径或 provider 配置。
- observation 进入正式 artifact 前必须经过 schema、大小、enum、内容和 provenance 验证；Tool 返回的指令一律视为不可信数据。

### 2.8 学习事实与 provenance

- Tool observation 不是课程事实或学习事实，不能直接写 mastery、Weakness、Memory、Review Item、Completion 或 Learning Event。
- Lesson 内容只有通过来源/citation、科学 verification provenance、公式 schema 和覆盖 validator 后才成为 Lesson Version。
- Practice 只有正式 Attempt/Feedback 才按现有规则产生 Learning Event；Tool success/failure 本身不投影掌握度。
- 编程分数由不可变测试和确定性规则产生；LLM 反馈不能改分。
- Tutor answer 区分 course citations、code observation 和 science observation；三者不能互相冒充。

### 2.9 协议、readiness 与 schema

- 自托管 execution MCP 固定 `2025-11-25`；Wolfram Cloud MCP 允许官方当前协商的 `2025-03-26`。继续使用稳定 Python SDK v1 `<2`，新增协议版本需单独兼容性验证。
- 使用公开 SDK API 与 Streamable HTTP；不依赖私有属性或手写协议 parser。
- capability probe 通过真实 initialize/list_tools/schema 检查写 Postgres TTL projection；API 只读脱敏 projection。Wolfram 准入 hash 只覆盖获准的两个 Tool；官方 Tool 未声明 `outputSchema` 时以规范化空 schema 纳入 hash，并由产品对实际 TextContent 执行大小、类型和不可信 observation 校验。远端额外 Tool 不进入授权面。enabled 不等于 ready。
- 每个 Job/Turn 固定 verified schema hash；worker 在调用前 compare-only，漂移时 `schema_drift` 且零 `call_tool`。
- 产品 Postgres Job/Turn/Attempt 仍是异步事实，Redis 只投递，MCP Tasks/session 不持久化为产品权威。

### 2.10 队列和执行拓扑

- Code Lab、Practice coding grading、Practice generation verification、Lesson generation 和 Tutor 使用各自已有业务 Job/Turn；不为每次 Tool Call创造第二套相互竞争的状态机。
- 长任务在调用前后 heartbeat，并在最终提交前重检 owner、lease、status、scope、capability、authorization 和 schema snapshot。
- duplicate delivery 不重复调用；只有稳定临时基础设施错误可自动重试。晚到结果、失去 lease 或取消后的结果全部丢弃。
- Judge0/Piston 只运行在 Windows 宿主机内的独立 Ubuntu VM。VM 不挂载项目目录/secret，禁止访问 Postgres、Redis、Qdrant、存储和公网；主 Compose 只访问固定 execution API。

### 2.11 数据、trace 与删除

- 私有 Tool I/O 归属于 Lesson Job、Practice Item/Attempt、Tutor Turn 或 Code Lab Run；不得进入普通日志、公开 trace 或脱敏运行摘要。
- trace 只记录 capability/tool/version/schema hash、ordinal、状态、耗时、大小、稳定错误码和是否实际调用。
- 编程题 hidden tests 是服务端私有评分材料；用户删除 Set/Course/Workspace 时一并硬删除。
- 删除 owner 时先禁止新调用并使 active worker 失去最终提交权，再清理 authorization、Tool I/O、Job/Run/association 和 trace。
- 本地删除不等于远程 Wolfram 删除；管理员必须接受供应商条款，UI/部署文档披露远程保留边界。

## 3. 预算决策

- Tutor：8 decision step、3 次 evidence search、MCP 总计 3 次，其中 code 最多 2 次、science 最多 3 次。
- Lesson Writer：每 Job science 最多 3 次，不增加既有 12 次 provider call 上限。
- Practice Set generation：science 最多 3 次；每个 coding item 最多一次参考解验证任务。
- Coding Attempt：一次正式 execution；基础设施 retry 复用同一 Attempt/Job，不新增正式结果。
- Scientific grading：每题最多 2 次 science call。

这些是 attempt 级硬上限。实现可以降低部署默认值，但提高量级、允许并行 Tool Call 或加入新语言/Tool 必须重新评审。

## 4. 备选方案

### 4.1 只保留独立代码实验室

拒绝作为最终产品合同。它适合自由实验，却让编程题和 Tutor 无法利用可验证执行，MCP 只剩演示入口。

### 4.2 用户先运行，再把摘要交给 Tutor

保留为可选显式上下文，但拒绝作为唯一路径。Tutor 在 Turn 授权内自行运行最小代码更符合连续辅导，也能准确解释真实结果。

### 4.3 用 LLM 判断代码正确性

拒绝。编程分数必须来自固定测试；LLM 只能解释结果。

### 4.4 用 Wolfram 渲染公式

拒绝。公式排版是本地、确定性的表现层能力，不应产生远程调用、外发或可用性依赖。

### 4.5 所有科学题都调用 Wolfram

拒绝。能本地确定性判定或课程 answer spec 已足够时零调用，避免成本、延迟和不必要外发。

### 4.6 任意 MCP Registry 与动态 Tool discovery

拒绝。Registry 收录不等于产品审核，动态能力会破坏数据、成本、删除、prompt injection 和测试合同。

## 5. 后果

正面：

- MCP 从独立演示入口进入课程、练习和 Tutor 的真实学习路径。
- 公式显示不依赖远程服务；代码分数和科学核验拥有可重复依据。
- 用户仍能逐业务动作控制外发和资源使用，Agent 自主性被固定 capability、schema 和预算包围。
- 课程引用、Tool provenance 与学习事实保持可解释分离。

代价：

- 需要扩展 Lesson/Practice/Tutor artifact、授权快照、队列、删除图、eval 和前端。
- 编程题 hidden tests、harness version 和部分得分引入新的服务端私有事实。
- Tutor 8-step 工具路径增加延迟、成本和失败组合。
- Wolfram 进入 Lesson/Practice 后，外发说明与真实远程 smoke 范围扩大。

## 6. 合同演进

- 本 ADR 接受后覆盖 ADR 006 首版中“代码运行始终由用户按钮触发”和“Tutor 没有 run_code 权限”的决定。
- ADR 002 的普通简答 Grader 无 Tool 决策继续有效；只有本 Spec 标记的 scientific/coding item 进入新增工具路径。
- Stage 3 ADR 006 的 Lesson Writer 单角色、来源边界、预算所有权和原子提交继续有效；science verification 是受控 phase，不是新 Agent。
- ADR 005 的教学 Skill 版本、Memory/citation 边界继续有效；Tool plan 是 v3 后续修订的一部分，不开放通用 SkillTool。

## 7. 人工 Gate（已接受）

接受本 ADR 意味着确认：

1. 公式渲染采用本地 KaTeX + `mhchem`，不是 MCP。
2. 两项 capability 继续由管理员审核，不开放任意 MCP。
3. Agent 可以在 Lesson、Practice 和 Tutor 的固定合同内调用 Tool；用户按 Job、交卷或 Turn 授权。
4. Tutor 每 Turn 最多 3 次 MCP、代码最多 2 次，decision step 调整为 8。
5. 编程题使用 hidden tests 和确定性评分；Tool/LLM 不直接写学习事实。
6. Wolfram 只验证或计算，不扩大课程来源；失败时不伪造结论或分数。
7. 题型适配由 Lesson objective/evidence 决定；用户选择不强迫 provider 生成无关编程/科学题，不适合时明确失败。
8. 代码工作台采用统一、正式的编辑器组件，并为代码与 Tutor 提供保留状态的专注模式。
9. 接受新增数据、队列、删除、部署和验证成本，并在实现前重写 GLM 任务包。

以上决策已于 2026-07-21 获人工接受。实现必须使用新的增量任务包，不得继续执行 2026-07-19 首版任务包。

## 8. 已确认的演示部署拓扑

代码执行后端继续采用同一台 Windows 开发机中的独立 Ubuntu VM：建议 2-4 vCPU、4-8 GB 内存；不挂载项目目录或产品 secret，默认无公网，并禁止访问 Postgres、Redis、Qdrant 和产品存储。Judge0/Piston 的 privileged 要求只存在于隔离 VM，不并入主产品 Compose。

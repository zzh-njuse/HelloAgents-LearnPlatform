# Stage 4 Slice 4 MCP 事实盘点

状态：2026-07-21 已修订；作为 Spec 004 / ADR 006 修订事实输入

日期：2026-07-19

## 1. 仓库现状

- `hello_agents/mcp/` 已有通用 MCP client/server prototype，支持内存、stdio、SSE 和 Streamable HTTP，但不拥有 Workspace、授权、删除、队列或产品 trace。
- `academic_companion/mcp_extensions/` 已有 arXiv 与 Semantic Scholar 研究原型，不能直接定义产品合同。
- Product API 尚无 MCP capability、connection、invocation 或 result schema；现有 `AgentRun` / `AgentToolCall` 只能作为 trace 模式参考。
- 当前 Tutor 只有受控 RAG 检索权限，没有经过管理员审核、Workspace policy 和按 Turn 授权的 MCP Tool 路径。
- 正式依赖中没有固定 MCP SDK 版本；framework prototype 不能直接注册到产品 Tutor。

## 2. 当前 MCP 标准事实

- 截至 2026-07-19，最新正式规范仍为 `2025-11-25`；`2026-07-28` 已冻结为 Release Candidate，尚未正式发布。
- `2026-07-28` RC 转向无状态协议核心、Extensions、MCP Apps 和更强授权约束，并调整 Tasks、Roots、Sampling 与 Logging 的定位。
- 本 Slice 固定正式版 `2025-11-25` 与稳定 SDK；实现边界不得依赖 RC API，但数据模型和 adapter 不保存协议 Session 假设，以降低后续升级成本。
- Tool 通过 JSON Schema 描述输入并可声明 `outputSchema`；结构化结果仍须由产品 adapter 再次验证。
- Tool annotations 只是提示，不能代替管理员准入、用户授权、参数白名单或网络隔离。
- MCP 统一的是发现、调用和结果交换，不自动解决 server 信任、数据外发、重试、删除、计费与产品语义。
- MCP Tasks 不作为产品异步事实；本项目继续使用 Postgres Job、Redis delivery 和 worker lease。

参考：

- [MCP 2025-11-25 Transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP 2026-07-28 Release Candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- [MCP Tool schema 与 annotations](https://modelcontextprotocol.io/specification/2025-11-25/schema)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 3. MCP 产品模型

本 Slice 不实现“Agent 面向整个 MCP 市场自由发现并调用工具”。采用以下受控模型：

1. 平台管理员安装、配置并审核 MCP server。
2. 产品把审核后的 Tool 映射为固定 capability，而不是向模型暴露任意 server、URL 和 Tool 描述。
3. Workspace policy 决定 capability 是否可用。
4. 用户按 Run 或按 Tutor Turn 授权。
5. Agent 只在该次授权和固定白名单内自主选择 Tool。
6. Tool 结果是不可信观察，不自动成为课程事实或学习事实。

### 3.1 注册、费用与许可证事实

- Judge0 CE 自托管不需要注册或按调用付费，采用 GPLv3；若改用 Judge0 Cloud/其他托管入口，则需要账号/API key，并按对应套餐处理。
- Judge0 CE 是执行后端而不是现成的本项目 MCP server；仍需产品 adapter。其官方部署可能要求高权限容器，因此真实后端接入必须先通过独立安全 spike，不能直接复制进主 Compose。
- Wolfram Cloud MCP 官方文档提供可直接连接的 Streamable HTTP endpoint，并称“有限个人使用免费”；示例配置没有要求 API key。
- 免费 Cloud MCP 定位为小规模、非持久、单次远程调用。若平台转为组织、商业、共享或高用量部署，必须向 Wolfram 核实 Enterprise/AI Access 条款和费用，不能把个人免费额度当作产品永久合同。
- Slice 4 的自动化不得依赖免费远程服务；真实 Wolfram smoke 仍须人工确认，默认使用 fake MCP。

## 4. 已选能力

### 4.1 自托管代码实验室

- 产品拥有固定 execution MCP adapter；adapter 后端采用成熟的自托管多语言执行引擎，Judge0 为首选候选，不自行发明编译与沙箱核心。
- 首版语言白名单为 Python、Java 和 C++。
- 独立实验室仍由用户编辑代码并点击“运行”；2026-07-21 修订允许 Tutor、Practice Generator 和 Practice Grader 在各自授权、schema 与预算内自主请求执行，不能获得通用执行权限。
- MCP Tool 使用固定 `run_code(language, source_code, stdin)` 合同。
- 不安装依赖，不开放 shell、文件上传、宿主目录、产品凭据或公网访问。
- 代码与输出仅保存在所属 Workspace 的私有产品记录中；执行服务不成为新的持久事实来源。

这是自托管 MCP：MCP server、执行后端和数据边界由部署者控制，主要验证隔离、可替换执行后端和本地数据治理。

### 4.2 Wolfram 科学工具

- 平台管理员显式配置并审核 Wolfram 远程 MCP；未配置时 capability 为 unavailable，不伪造降级结果。
- 首版只准入 `WolframAlpha` 和 `WolframContext`，禁止可执行任意 Wolfram Language 的 `WolframLanguageEvaluator`。
- 覆盖数学、物理和通用化学计算；首版不额外接入 PubChem。
- 用户在发送 Tutor Turn 前启用“允许本次使用科学工具”。授权只对该 Turn 生效，发送或切换 scope 后清除。
- Tutor Agent 可在该 Turn 内自主判断是否调用管理员白名单中的 Wolfram Tools，最多 3 次；无授权时不得调用。
- 只外发解决当前问题所需的用户问题和最小上下文，不发送课程原文、Memory 全量、代码、API key、内部 ID、prompt 或 provider 配置。
- 回答必须区分课程引用与科学工具结果，并标记外部工具参与；Wolfram 结果不能直接更新 mastery、Weakness、Memory、Review Item 或 Lesson Completion。

这是远程 MCP：server 由外部供应商运行，主要验证逐 Turn 授权、最小化外发、远程失败降级和供应商信任边界。

## 5. 为什么不开放任意 MCP

- Registry 收录不等于经过本产品安全审核。
- 动态 Tool 描述可能包含提示注入、重名、语义漂移或未知数据外发要求。
- 任意 server 会让成本、凭据、可用性、删除和日志合同无法稳定验证。
- 产品用户需要“代码实验室”和“科学工具”，而不是 endpoint、transport 和 `tools/call` 管理界面。

未来可增加管理员 MCP catalog，但每项 capability 仍须单独 Spec/ADR、准入测试和产品 adapter。

## 6. 原型不可直接复用

- framework `MCPClient` 允许动态 transport/config 和环境变量，不符合固定 server、Tool 与凭据边界。
- prototype 把结果简化成自由文本，缺少产品所需的 output schema、大小限制、版本快照和删除权威。
- prototype 的 console 输出和通用异常不符合日志脱敏合同。
- 学术检索扩展既不证明代码隔离，也不能替代 Wolfram 的远程授权合同。

## 7. 已确认与待确认

已由人工确认：

1. 管理员安装并审核 MCP，产品建立 capability 白名单，Agent 只在已批准能力中按次授权调用。
2. 代码 MCP 验证自托管与隔离；独立实验室由用户主动调用，Lesson/Practice/Tutor 只在新 Spec/ADR 的固定授权与预算内调用。
3. Wolfram MCP 验证远程服务和 Agent 受限自主选用；Tutor 按 Turn 授权，Lesson/Practice 按 Job 或交卷授权。
4. 不实现任意 MCP 市场；MCP 结果不直接成为学习事实。

2026-07-21 修订 Gate 已确认：

1. 公式使用本地 KaTeX + `mhchem`，不把 Wolfram 当渲染服务。
2. 编程题固定 Python、Java、C++，使用隐藏测试与确定性评分。
3. Lesson/Practice generation 的 Wolfram 按 Job 授权，Practice grading 在交卷时一次确认。
4. Tutor 代码与科学分别按 Turn 授权，MCP 总计最多 3 次，decision step 调整为 8。
5. 接受扩展到课程、练习和 Tutor 后新增的 schema、队列、删除、VM 与远程服务验证成本。

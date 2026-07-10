# 0R-B：原型合约盘点

状态：完成
日期：2026-07-10
方法：静态源码审计；未调用 LLM、Qdrant 或真实 API。

## 范围与边界

`academic_companion` 是可复用的领域/原型资产，不是 Stage 1 产品应用；其当前 API 路由也不是公开兼容性承诺。本盘点保留有价值的合约，并在产品 API 出现前明确其短板。

## 当前原型 API

`academic_companion/api/server.py` 中的 app factory 将两个 router 挂在 `/api` 下，仅为常见本地 Vite 端口启用 CORS，并提供下列接口。

| 接口 | 合约 | 产品处置 |
|---|---|---|
| `GET /` | 含原型 URL 的 API 发现对象 | 废弃；产品根路径不应是原型目录 |
| `GET /api/health` | `{status, version, modes}` | 用产品 `/health` 存活检查替换 |
| `POST /api/chat/stream` | `ChatRequest` 到 SSE | 仅保留为后续 adapter 参考 |
| `POST /api/chat` | `ChatRequest` 到 `{mode, response, session_id}` | Stage 1 不提供产品路由 |
| `GET /api/knowledge/status` | Qdrant collection 统计和配置 URL | 废弃；产品 API 不得暴露后端 URL |
| `GET /api/knowledge/chapters` | 扫描内置 CS-Base Markdown 树 | 作为未来 catalog adapter，而非复制路由 |

`ChatRequest` 包含 `mode: "learning" | "research"`、必填的 `message` 和默认为 `"default"` 的 `session_id`。非法模式返回 HTTP 400。非流式运行时错误会以异常文本转为 HTTP 500。

### Session 与执行行为

- Learning 请求使用按客户端 `session_id` 索引的无上限内存字典；每项保存一个温度为 0.5、`max_steps=8` 的 `LearningAgent`/`HelloAgentsLLM`。
- Research 每个请求新建一个温度为 0.3 的 `ResearchOrchestrator`；`_research_sessions` 被声明但未使用。
- Learning 可经当前 academic agent 写入 working、user-model、episodic 和 semantic 状态；这些原型持久化不是产品拥有的 Postgres 状态。
- Research streaming 在 async route 内调用同步 orchestrator，可能阻塞事件循环；其展示管线不是 Stage 1 产品工作流。

## SSE 线协议

`StreamEvent.to_sse()` 输出一个 `event:` 名称和一行 JSON `data:`。JSON 信封含 `type`、UNIX 浮点 `timestamp`、`agent_name` 和 `data` 对象。已知事件类型为 `agent_start`、`agent_finish`、`step_start`、`step_finish`、`tool_call_start`、`tool_call_finish`、`llm_chunk`、`thinking` 与 `error`。

聊天路由额外输出 `academic_companion` 的起止事件，将 generator 异常捕获成 `error` 事件，并以响应头关闭缓冲。它只在迭代 research 输出时尝试发送 heartbeat，因此不是可靠的空闲心跳协议。

该信封可作为未来 agent-run 特性的 adapter/reference 合约，但不会成为 Stage 1 HTTP 合约，因为 Stage 1 不含 chat 或 agent-run 接口。

## 当前原型 Web

React/Vite 应用使用同源 `/api`，开发时代理到 8000 端口。`createSSEStream` 使用 `fetch` 加 `ReadableStream`，发送 POST JSON body，并解析一行 `event:` 后跟一行 `data:` JSON。它通过 `AbortController` 支持取消，但没有重连、event ID、重试或多行 data 支持。

UI 仅在 React 内存中保留消息；它生成一个浏览器 UUID session，渲染流式文本、thinking block 与 tool call，并能把错误显示到 assistant 消息中。Research panel 的步骤会在请求开始时重置，但当前 SSE 事件不会更新其步骤状态。

可参考的内容是 Markdown/数学渲染、流式消息行为、POST-SSE 解析模式、本地代理和基础 TypeScript 类型。它不适合 Stage 1 shell，因为它是 chat-first、不持久化产品状态、并依赖原型路由。

## 明确的迁移规则

| 资产 | 规则 |
|---|---|
| `hello_agents` stream event | 保留为 framework 级事件原语 |
| `LearningAgent` 和 research orchestrator | Stage 1 后的 adapter 候选；当前不得嵌入产品 router |
| 原型 chat 路由 | 不复制到 `apps/api`；后续仅从已批准 spec 引入版本化产品合约 |
| Qdrant status 路由 | 不复制；readiness 仅可报告布尔/详情，不能返回连接 URL 或凭据 |
| CS-Base chapter scanner | 仅可在未来具备所有权元数据的 catalog 边界后复用 |
| 原型 React chat 组件 | 仅选择性参考；产品首屏不得成为 chat UI |

## 后续风险

- 原型 CORS、内存 session、异常详情和原始 Qdrant URL 暴露都不是产品安全默认值。
- API 依赖集仍是隐式的。
- 在引入任何产品 agent streaming 接口前，服务端和 SSE parser 都需要合约测试。
- 内置 CS-Base、八股与 LeetCode 数据继续作为 fixture 和迁移样本，不作为专用产品数据模型的基础。

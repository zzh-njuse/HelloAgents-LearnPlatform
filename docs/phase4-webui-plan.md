# Phase 4: WebUI + Bug Fixes

> **版本**: v1.0
> **日期**: 2026-05-21
> **状态**: 设计中，等待开发

---

## 1. 前置 Bug 修复

### Bug 1: JSON 解析频繁失败 🔴

**现象**：`demo_research.py` 场景 4 中，四个子 Agent 输出全部 "JSON 解析失败，降级为原始文本"。

**根因**：[orchestrator.py:237-243](academic_companion/agents/research/orchestrator.py#L237-L243) 使用 `run_as_subagent(return_summary=True)` + `result.get("summary")`。`_generate_subagent_summary()` 在 [agent.py:1100-1137](hello_agents/core/agent.py#L1100-L1137) 将子 Agent 完整输出截断到 **500 字符**并包裹在诊断模板中。子 Agent 的 JSON 块在响应末尾（自然语言 + `---` + JSON），永远在 500 字符之后，导致 `_parse_structured_output()` 找不到 JSON。

**修复**（2 行）：
```python
# orchestrator.py:238 — return_summary=True → return_summary=False
# orchestrator.py:243 — result.get("summary", ...) → result.get("result", ...)
```

当 `return_summary=False` 时 [agent.py:984-988](hello_agents/core/agent.py#L984-L988) 返回完整 untruncated 输出。

### Bug 2: SearchAgent 步数限制过紧 🟡

**现象**：Scene 3 SearchAgent "无法在限定步数内完成这个任务"。

**根因**：[config.py:72](academic_companion/config.py#L72) `subagent_max_steps: int = 6`，搜索需多轮 MCP 调用（arXiv + SemanticScholar）+ 结果整理。

**修复**（2 行）：
- `config.py:72` → `subagent_max_steps: int = 10`
- `search_agent.py:88` → 构造器默认 `max_steps=10`

---

## 2. FastAPI 后端

### 2.1 架构

```
academic_companion/api/
├── __init__.py
├── server.py          # FastAPI 组装 + CORS + health
├── routes_chat.py     # /api/chat/stream (SSE), /api/chat (非流式)
└── routes_knowledge.py # /api/knowledge/status, /api/knowledge/chapters
```

### 2.2 端点设计

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/chat/stream` | SSE 流式聊天（`{mode, message, session_id}`） |
| `POST` | `/api/chat` | 非流式回落 |
| `GET` | `/api/knowledge/status` | Qdrant collection 统计 |
| `GET` | `/api/knowledge/chapters` | CS-Base 章节列表 |

### 2.3 SSE 事件流

参考 [streaming.py](hello_agents/core/streaming.py) `StreamEvent.to_sse()` 格式：

```
event: agent_start
data: {"type":"agent_start","timestamp":...,"agent_name":"...","data":{...}}

event: step_start        ← 仅研究模式
data: ...

event: tool_call_start
data: ...

event: tool_call_finish
data: ...

event: llm_chunk         ← 流式文本
data: {"type":"llm_chunk","data":{"chunk":"..."}}

event: agent_finish
data: ...
```

### 2.4 Research Mode 流式化

`ResearchOrchestrator` 继承自 `PlanSolveAgent`，其 `run()` 改为同步串行子 Agent pipeline。新增 `run_streaming()` 方法（~40 行），在 pipeline 步骤前后 emit 事件：

```
AGENT_START → (STEP_START → run sub-agent → STEP_FINISH) × 4 → AGENT_FINISH
```

### 2.5 依赖

```bash
pip install fastapi uvicorn python-multipart
```

---

## 3. React 前端

### 3.1 技术栈

- Vite + React 19 + TypeScript
- react-markdown + remark-gfm + rehype-katex (Markdown + LaTeX)
- CSS Modules (组件级样式)

### 3.2 目录结构

```
academic_companion/webui/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts          # proxy /api → localhost:8000
└── src/
    ├── main.tsx
    ├── App.tsx             # 主布局
    ├── App.module.css
    ├── components/
    │   ├── ChatView.tsx     # 消息列表 + 输入
    │   ├── MessageCard.tsx  # Markdown 渲染 + ToolCallCard/ThinkingBlock
    │   ├── ToolCallCard.tsx # 可折叠工具调用卡片
    │   ├── ThinkingBlock.tsx # 可折叠思考过程
    │   ├── ModeSwitcher.tsx # 学习/研究模式切换
    │   └── ResearchPanel.tsx # Pipeline 四步进度
    ├── hooks/
    │   └── useSSE.ts        # SSE 生命周期管理
    ├── services/
    │   └── api.ts           # API 封装 (fetch + ReadableStream)
    └── types/
        └── index.ts         # 共享类型定义
```

### 3.3 SSE 客户端

`EventSource` 仅支持 GET，本项目使用 `fetch` + `ReadableStream`（POST-based），参考 [examples/sse_client.html](examples/sse_client.html#L137-L194) 的解析逻辑。

### 3.4 核心组件职责

| 组件 | 职责 |
|------|------|
| `ChatView` | 消息列表（自动滚底）+ 输入框 + 发送/取消 |
| `MessageCard` | `react-markdown` 渲染正文 + 内嵌 `ToolCallCard` + `ThinkingBlock` |
| `ToolCallCard` | 可折叠展开（工具名 + 参数 + 结果），三态图标（运行中/成功/失败） |
| `ThinkingBlock` | `<details>` 折叠思考过程 |
| `ModeSwitcher` | 学习/研究双按钮切换 |
| `ResearchPanel` | Pipeline 四步进度条（pending→running→completed/failed） |

---

## 4. 执行顺序

```
Part A — Bug Fixes (先做，无依赖)
├── A1: orchestrator.py 2 行 — JSON 解析修复
├── A2: config.py + search_agent.py — 步数修复
└── 验证: 重跑 demo_research.py

Part B — FastAPI 后端 (依赖 A1)
├── B1: pip install fastapi uvicorn
├── B2: routes_chat.py → routes_knowledge.py → server.py
├── B3: ResearchOrchestrator.run_streaming() 新方法
└── 验证: curl SSE 端点

Part C — React 前端 (依赖 B 的 API 契约)
├── C1: npm create vite + install deps
├── C2: types → services → hooks
├── C3: 组件逐个实现 → App 组装
└── 验证: 浏览器端到端测试

Part D — Polish
├── D1: 多轮对话 session 保持
├── D2: 响应式 + 暗色模式
└── D3: 加载/错误/空状态
```

---

## 5. 参考文件

- [streaming.py](hello_agents/core/streaming.py) — StreamEvent + StreamEventType + to_sse() + StreamBuffer
- [fastapi_sse_server.py](examples/fastapi_sse_server.py) — 完整 FastAPI SSE 示例 (177 行)
- [sse_client.html](examples/sse_client.html) — 原生 JS SSE 客户端 (286 行)
- [streaming-sse-guide.md](docs/streaming-sse-guide.md) — SSE 协议完整文档 (640 行)
- [agent.py:880-988](hello_agents/core/agent.py#L880-L988) — run_as_subagent 完整实现
- [config.py](academic_companion/config.py) — AcademicConfig 配置单例
- [project-proposal-academic-ai-companion.md](docs/project-proposal-academic-ai-companion.md) — 项目立项文档

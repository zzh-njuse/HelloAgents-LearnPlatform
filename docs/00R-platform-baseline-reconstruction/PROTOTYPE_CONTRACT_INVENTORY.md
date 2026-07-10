# 0R-B Prototype Contract Inventory

Status: complete
Date: 2026-07-10
Method: static source audit; no LLM, Qdrant, or live API calls were made.

## Scope And Boundary

`academic_companion` is reusable domain/prototype material. It is not the Stage 1 product application and its current API routes are not a public compatibility promise. This inventory preserves useful contracts and makes shortcomings explicit before a product API is introduced.

## Current Prototype API

The app factory in `academic_companion/api/server.py` mounts both routers under `/api`, enables CORS only for common local Vite ports, and exposes the following surface.

| Endpoint | Contract | Product disposition |
|---|---|---|
| `GET /` | API discovery object with prototype URLs | retire; product root is not a prototype directory |
| `GET /api/health` | `{status, version, modes}` | replace with product liveness at `/health` |
| `POST /api/chat/stream` | `ChatRequest` to SSE | preserve only as later adapter reference |
| `POST /api/chat` | `ChatRequest` to `{mode, response, session_id}` | no Stage 1 product route |
| `GET /api/knowledge/status` | Qdrant collection statistics and configured URL | retire; product API must not expose backend URLs |
| `GET /api/knowledge/chapters` | scans bundled CS-Base Markdown tree | future catalog adapter, not route copy |

`ChatRequest` has `mode: "learning" | "research"`, required `message`, and `session_id` defaulting to `"default"`. Invalid modes return HTTP 400. Non-streaming runtime errors become HTTP 500 with the exception text.

### Session And Execution Behavior

- Learning requests use an unbounded in-memory dictionary keyed by client `session_id`; each entry holds a `LearningAgent` using `HelloAgentsLLM` with temperature 0.5 and `max_steps=8`.
- Research creates a new `ResearchOrchestrator` per request with temperature 0.3. `_research_sessions` is declared but unused.
- Learning can record working, user-model, episodic, and semantic state through the current academic agent. That prototype persistence is not product-owned Postgres state.
- Research streaming invokes synchronous orchestration inside an async route; it can block the event loop. Its display pipeline is not a Stage 1 product workflow.

## SSE Wire Contract

`StreamEvent.to_sse()` emits an `event:` name followed by one JSON `data:` line. The JSON envelope contains `type`, a UNIX-float `timestamp`, `agent_name`, and a `data` object. Known event types are `agent_start`, `agent_finish`, `step_start`, `step_finish`, `tool_call_start`, `tool_call_finish`, `llm_chunk`, `thinking`, and `error`.

The chat route adds an outer `academic_companion` start and finish event, catches generator exceptions as an `error` event, and sets headers to disable buffering. It only attempts a heartbeat while iterating research output, so it is not a reliable idle-heartbeat protocol.

This envelope is a useful adapter/reference contract for a later agent-run feature. It is not adopted as the Stage 1 HTTP contract because Stage 1 has no chat or agent-run endpoint.

## Current Prototype Web

The React/Vite app uses same-origin `/api` and proxies it to port 8000 in development. `createSSEStream` uses `fetch` plus a `ReadableStream`, sends a POST JSON body, and parses one `event:` line followed by one `data:` JSON line. It supports cancellation through `AbortController`, but has no reconnect, event-ID, retry, or multi-line-data support.

The UI retains messages only in React memory. It creates one browser UUID session, renders streamed chunks, thinking blocks, and tool calls, and can display an error inside the assistant message. Research panel steps reset when a request starts, but current SSE events do not update those step states.

Useful source material: Markdown/math rendering, streaming-message behavior, POST-SSE parser pattern, local proxy setup, and basic TypeScript types. It is not suitable as the Stage 1 shell because it is chat-first, does not persist product state, and assumes prototype routes.

## Explicit Migration Rules

| Asset | Rule |
|---|---|
| `hello_agents` stream events | retain as framework-level event primitive |
| `LearningAgent` and research orchestrator | adapter candidates after Stage 1; do not embed in product routers now |
| Prototype chat routes | do not copy into `apps/api`; later introduce versioned product contract from approved spec |
| Qdrant status route | do not copy; readiness may report boolean/detail without connection URLs or credentials |
| CS-Base chapter scanner | reuse only behind a later catalog boundary with ownership metadata |
| Prototype React chat components | selective reference only; do not make product first screen a chat UI |

## Risks To Carry Forward

- Prototype CORS, in-memory sessions, exception details, and raw Qdrant URL exposure are not product-safe defaults.
- The API dependency set is implicit.
- The SSE parser and server both need contract tests before any product agent-streaming endpoint is introduced.
- Bundled CS-Base, interview-note, and LeetCode data remain test fixtures and migration samples, not the basis for a special product data model.

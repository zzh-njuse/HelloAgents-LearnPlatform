# ADR 001: Application Stack And Prototype Bridge

Status: proposed; implementation requires explicit confirmation
Date: 2026-07-10

## Context

The correct repository contains a reusable Python framework and a committed academic prototype, but no product application boundary. The mistaken repository demonstrated a plausible Stage 1 shell, yet its source was created against a different repository state and must not be transplanted wholesale.

## Decision

| Layer | Decision |
|---|---|
| API | FastAPI, Pydantic Settings, versioned `/api/v1` product routes |
| Persistence | SQLAlchemy 2.x synchronous sessions, Alembic, Psycopg 3, Postgres |
| Web | React, Vite, TypeScript, npm, committed lockfile |
| Operations | Docker Compose for Postgres, Qdrant, Redis, API, and Web |
| Logging | Structured, request-ID-aware, redacted server logging |
| Dependency ownership | Root metadata remains framework-only; `apps/api/requirements.txt` and `apps/web/package.json` own application dependencies |

The product API will be built in `apps/api/learn_platform_api`, with a read-only adapter boundary to `academic_companion`. Stage 1 will not mount or rewrite the prototype chat router and will not call an LLM as a health or capability test.

## Rationale

- FastAPI fits the Python framework boundary, while an independent application manifest avoids forcing Web/database dependencies on framework consumers.
- Synchronous SQLAlchemy is adequate for small workspace CRUD and avoids premature async database complexity before background jobs exist.
- Postgres establishes the accepted product source of truth; Qdrant and Redis remain supporting services.
- Vite/React fits an operational SPA and can selectively reuse prototype presentation ideas without inheriting chat-first architecture.
- The product owns a new versioned API contract. This prevents prototype CORS, raw exception detail, raw Qdrant URL exposure, and in-memory sessions from becoming public defaults.

## Consequences

- Stage 1 adds a small monorepo shape and several verification commands.
- Root `uv.lock` repair and framework test dependency policy remain a distinct follow-up from application dependency management.
- Product code may import stable framework/domain interfaces, but must not add product state or route semantics inside `hello_agents` or `academic_companion`.
- Future chat/SSE work needs its own spec and contract tests before the prototype envelope is adopted or evolved.

## Alternatives Rejected For This Stage

- Copying the mistaken Stage 1 tree directly: different baseline assumptions and package identity.
- Keeping `academic_companion/api` as product gateway: prototype-first, implicit dependencies, unsafe operational details.
- SQLite-first deployment: rejected by the accepted Postgres fact-source gate.
- Async SQLAlchemy, workers, and jobs: deferred until ingestion makes that complexity necessary.
- Chat-first Web: rejected because the product is a learning platform, not a dual-mode chat application.

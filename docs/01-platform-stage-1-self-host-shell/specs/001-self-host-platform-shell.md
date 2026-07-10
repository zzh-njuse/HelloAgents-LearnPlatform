# Spec 001: Self-Host Platform Shell

Status: draft; implementation requires explicit confirmation
Date: 2026-07-10

## Goal

Create a self-hostable product application around the existing framework and academic assets. The initial screen is an operational workspace workbench, not a dual-mode chat application.

## Product Boundary

`hello_agents/` is reusable framework code, `academic_companion/` is reusable academic/domain material and prototype reference, and `apps/api` plus `apps/web` are product code.

Product business state belongs in Postgres. Qdrant is rebuildable derived indexing infrastructure. Redis is non-authoritative coordination infrastructure. Neither prototype in-memory sessions nor bundled data trees become a product source of truth.

## In Scope

- `apps/api` FastAPI application with independent dependencies and tests.
- `apps/web` React/Vite/TypeScript application with independent npm lockfile.
- Docker Compose services: Postgres, Qdrant, Redis, API, and Web.
- Postgres migration and minimal `workspaces` table.
- Workspace list, create, and get API.
- Product liveness, readiness, and non-sensitive system-info endpoints.
- A read-only academic capability/catalog adapter that proves the product can depend on `academic_companion` without moving product code into it or calling an LLM.
- Web workbench showing readiness, workspace list, workspace creation, and an honest empty state for later material work.
- Request ID and structured, non-sensitive server logging.
- Stage-specific verification commands, review record, and self-host runbook.

## Out Of Scope

- Authentication, multi-user permissions, deletion semantics, and OAuth.
- Uploads, parsing, OCR, batch import, jobs, chunks, embeddings, or Qdrant writes. Those belong to Platform Stage 2 slices.
- Agent chat, SSE product endpoints, course reader, knowledge graph, exercises, spaced repetition, and run/cost analytics.
- Neo4j, a worker service, HTTPS/reverse proxy, and cloud deployment.
- A data model specialized for existing interview-note or LeetCode assets.

## Repository Layout

The implementation adds `apps/api/learn_platform_api`, `apps/api/alembic`, `apps/api/tests`, `apps/api/requirements.txt`, `apps/api/Dockerfile`, `apps/web`, root `docker-compose.yml`, and ignored runtime `storage/`. The package name deliberately differs from the mistaken repository so this repository establishes its own product identity.

## API Contract

| Method | Path | Required behavior |
|---|---|---|
| `GET` | `/health` | Process-only liveness; does not probe dependencies |
| `GET` | `/ready` | Reports Postgres, Qdrant, Redis, and storage-root checks as `ready` or `degraded`; no credentials or service URLs |
| `GET` | `/api/v1/system/info` | Non-sensitive product name, environment, and storage configured flag |
| `GET` | `/api/v1/workspaces` | Paginated workspace list, newest first |
| `POST` | `/api/v1/workspaces` | Create a workspace and collision-safe slug |
| `GET` | `/api/v1/workspaces/{workspace_id}` | Return one workspace or 404 |
| `GET` | `/api/v1/capabilities` | Read-only framework/academic capability categories; no LLM invocation |

`workspaces` contains `id`, `name`, unique `slug`, nullable `description`, `created_at`, and `updated_at`. Workspace deletion is intentionally absent.

## Web Contract

The first viewport must show a usable workbench: workspace navigation and selection; system readiness without backend addresses; workspace creation with client validation and server errors; and a current-workspace empty state that reserves later material capability without representing it as implemented.

Stage 1 does not route the Web through prototype `/api/chat` endpoints and does not surface a chat composer as the product center.

## Delivery And Verification

The implementation will be accepted only when API tests, Web lint/build, `docker compose config`, and `docker compose up --build` are recorded as applicable. The final runbook must state prerequisites, environment variables, migration command, local operator URLs, and shutdown/data-volume behavior. Substantive code changes require the repository review workflow in `AGENTS.md`; OCR results or a consciously declined review must be recorded in this stage's `reviews/` directory.

## Acceptance Notes

- The product API owns the versioned contract. Prototype route compatibility is not promised because the prototype has not been released as a product API.
- Compose validation must use clean configuration and named service volumes.
- Live stack acceptance must confirm Web load, Postgres-persisted workspace creation, and `/ready` distinction between healthy and degraded dependencies.

# Stage 1 Reference Adoption Matrix

Status: complete for planning; no reference code is migrated by this document.

The source reference is the mistaken repository's Legacy Phase 1 skeleton. Each outcome is deliberately limited to avoid importing its baseline mistakes.

| Reference asset | Decision | Stage 1 treatment | Reason |
|---|---|---|---|
| `apps/api` directory separation | adopt | recreate under `apps/api/learn_platform_api` | Preserves framework/product boundary while giving this repository its own name |
| FastAPI app factory and router split | adopt with rewrite | use as structural pattern only | Correct repo needs its own settings, package path, and contracts |
| Pydantic Settings pattern | adopt with rewrite | app-local settings and redaction | Appropriate for `.env`/Compose, but names and defaults need correct-repo review |
| SQLAlchemy sync + Alembic | adopt with rewrite | one workspace migration and repository-local tests | Matches Stage 1 complexity; no direct patch carries over |
| Workspace schema and collision-safe slugs | adopt behavior and tests | reimplement `id/name/slug/description/timestamps` | Useful minimal ownership root without importing unrelated code |
| Health, readiness, and system routes | adopt with rewrite | keep liveness/readiness distinction; redact output | Product readiness must not expose raw URLs or secrets |
| Request-ID middleware/logging | adopt conceptually | implement only non-sensitive logging | Aligns with confirmed review/operability process |
| Compose topology | adopt with rewrite | Postgres/Qdrant/Redis/API/Web with named volumes | Accepted data-role model is valid; images, env names, and build contexts need revalidation |
| API Dockerfile | reference only | rebuild against correct package/install layout | Direct copy assumes mistaken repository structure |
| Web workbench layout | selective reference | rebuild a workspace-first workbench | Direction is correct; source components need correct-repo ownership and QA |
| Prototype `academic_companion/webui` | selective reference | reuse only small streaming/Markdown ideas later | It is chat-first and outside Stage 1 scope |
| Prototype FastAPI chat routes | do not adopt in Stage 1 | leave in `academic_companion` | Chat/SSE lacks approved product spec and safe product defaults |
| Prototype knowledge status route | reject | replace with redacted product readiness | It exposes Qdrant URL and conflates operational detail with product API |
| Prototype chapter scanner | defer behind adapter | later catalog capability after ownership design | Bundled data is test material, not product facts |
| Wrong-repo Stage 1 tests | reuse scenarios, not files | write fresh product contract tests | Test intent is valuable; imports and fixtures are baseline-specific |
| Wrong-repo Stage 1 docs/runbook | superseded | use this stage's spec/ADR and write fresh runbook | Legacy wording and paths must not define correct repo |

## Required Reanalysis Before Any Copy

1. Verify dependency versions and lockfile policy against the 0R-A baseline.
2. Verify API names and response schemas against this Stage 1 spec.
3. Verify Docker build contexts and Windows-friendly local commands.
4. Verify database migration naming and fresh-Postgres upgrade behavior.
5. Verify Web accessibility, responsive layout, and absence of a chat-first first view.
6. Record OCR review after substantive code changes.

No row authorizes copying code unchanged. It authorizes only the specified implementation approach after the Stage 1 spec and ADR are accepted.

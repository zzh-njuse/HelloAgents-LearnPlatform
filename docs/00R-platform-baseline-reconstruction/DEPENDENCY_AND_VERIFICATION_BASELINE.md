# 0R-A Dependency And Verification Baseline

Status: complete
Date: 2026-07-10
Baseline commit: `4b81f92461ff05c3d78f4bc6cf54cd07a01ba753`

## Purpose

This record establishes the reproducible starting point before creating the product application. It describes three execution lanes rather than treating them as one installable application.

| Lane | Current authority | Result | 0R conclusion |
|---|---|---|---|
| `hello_agents/` framework | root `pyproject.toml`, `requirements.txt`, `uv.lock` | Core dependencies resolve with `uv --frozen`; root test tools are not declared | Preserve as reusable framework lane |
| `academic_companion/` prototype API | source imports only | FastAPI, Uvicorn, Qdrant client lack an independent manifest | Reference prototype, not runnable product entry |
| `academic_companion/webui/` prototype Web | `package.json`, `package-lock.json` | lint and production build pass | UI/streaming-contract reference, not Stage 1 Web |

## Environment Observed

- Windows host; default `python` is Anaconda Python 3.13.5.
- `uv` created an ignored local `.venv` with CPython 3.12.13 for the frozen framework lane.
- Node.js is 24.14.0 and npm is 11.9.0.
- Docker was not needed for this audit; Compose acceptance belongs to Stage 1.

The default Anaconda environment lacks declared `tiktoken`, so root test collection cannot start there. It is not an acceptance environment for this repository.

## Commands And Results

| Command | Result | Notes |
|---|---|---|
| `python -m pip check` | pass | No broken packages in the unrelated default environment |
| `python -m pytest -q` | blocked at collection | `ModuleNotFoundError: tiktoken` |
| `uv run --locked python -m pytest -q` | blocked before execution | `uv.lock` is stale relative to `pyproject.toml` |
| `uv run --frozen python -m pytest --collect-only -q` with temporary `pytest` and `pytest-asyncio` | pass | 231 tests collected on CPython 3.12.13 |
| focused offline framework suite | pass | 155 passed, 4 skipped in 3.81 seconds |
| `npm.cmd run lint` in `academic_companion/webui` | pass | Existing prototype lint baseline |
| `npm.cmd run build` in `academic_companion/webui` | pass with warning | Largest JS chunk is 620.56 kB, above Vite's 500 kB warning threshold |

The focused suite used `uv run --frozen --with pytest --with pytest-asyncio` over lifecycle, circuit-breaker, custom-tool, file-tool, LLM-function-calling, observability, research-note, session-persistence, skills, subagent, todo, tool-filter, and tool-response tests.

Skipped cases require a real LLM configuration. `tests/test_all_agents.py`, real-provider cases, and optional MCP/external-tool cases are not a deterministic local acceptance suite; they remain distinct from product Stage 1 acceptance.

## Dependency Findings

1. Root package dependencies include `tiktoken`, but the default host Python does not provide it. `uv --frozen` resolves the declared framework runtime.
2. Root test dependencies are implicit. `pytest` and `pytest-asyncio` are needed by the suite but are neither a project dependency group nor locked.
3. The lock is not synchronized with root project metadata. `--frozen` can use the existing lock, while `--locked` correctly refuses it.
4. Qdrant support is lazy-imported in `hello_agents/storage/qdrant_store.py`; FastMCP is likewise optional. Neither belongs in the framework mandatory set merely because the prototype can use it.
5. The prototype API imports `fastapi`, `uvicorn`, and `qdrant_client`, but no application-scoped dependency manifest declares them. This prevents a reliable API startup command today.
6. The prototype Web owns a valid npm lockfile, but its built output indicates a future bundle-splitting review, not a Stage 0R blocker.

## Baseline Decisions

- Do not rewrite the root lockfile during reconstruction. A dependency-only change must first decide whether framework test tooling belongs in a dev dependency group and regenerate the lock in a dedicated reviewable change.
- Do not add prototype API packages to the framework package. Stage 1 owns an independent `apps/api/requirements.txt`, as recorded in its draft ADR.
- Use `uv run --frozen --with pytest --with pytest-asyncio` for the temporary framework verification lane until the dependency decision is implemented.
- Treat the focused suite as the current deterministic framework gate; run real-provider and external-tool tests only with explicit runtime configuration and separately recorded results.

## Exit Criteria Met

- Current framework, prototype API, and prototype Web install boundaries are identified.
- A reproducible framework collection command and offline passing subset are recorded.
- Prototype API undeclared runtime dependencies are known before any product application is created.

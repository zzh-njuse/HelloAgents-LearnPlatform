"""MCP Execution Server — Streamable HTTP per ADR 006 §2.3.

Exposes the fixed ``run_code`` Tool over MCP protocol version 2025-11-25.
The server does NOT publish to the host network in the main Compose;
the product worker connects via the internal Docker network.

This server does NOT import from ``apps.api``.

Per correction 005 §3.1 point 4: provides a fixed ``/readyz`` endpoint
that reports backend readiness without exposing URLs or credentials.
This is NOT a Tool — it is an internal health endpoint for the probe.

Per correction 008 §2: infrastructure failures (backend unavailable,
backend timeout, invalid backend result) are returned as MCP Tool
errors (isError=true) with stable sanitized error codes. They are
NEVER disguised as user program runtime_error results.

Per correction 008 §3: uses the public low-level Server API with
official Streamable HTTP transport to register the Tool with the
exact canonical inputSchema and outputSchema from the shared contract.
No access to private FastMCP attributes (_mcp_server, _tool_manager, etc.).
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    Tool as McpTool,
    TextContent,
    CallToolResult,
    INTERNAL_ERROR,
)

from adapter import (
    ExecutionAdapter,
    RunCodeInput,
    RunCodeOutput,
    BackendUnavailableError,
    InvalidToolResultError,
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    SERVER_NAME,
    TOOL_NAME,
    TOOL_DESCRIPTION,
)

logger = logging.getLogger("mcp_execution_server")

# ---------------------------------------------------------------------------
# Stable sanitized error codes — never expose raw exceptions, URLs, or
# internal paths in Tool error responses (correction 009 §2).
# The server returns ONLY the stable code string — no detail, no raw text.
# ---------------------------------------------------------------------------

_STABLE_ERROR_CODES = frozenset({
    "backend_unavailable",
    "backend_timeout",
    "invalid_tool_result",
    "invalid_input",
})


def _sanitize_error(code: str) -> str:
    """Return a stable error code, or 'backend_unavailable' if unknown.

    Per correction 009 §2: the server outputs ONLY the stable code.
    No detail appending, no raw text propagation.
    """
    if code in _STABLE_ERROR_CODES:
        return code
    return "backend_unavailable"


# ---------------------------------------------------------------------------
# Server setup — public low-level Server API (correction 008 §3)
# ---------------------------------------------------------------------------

# Read backend URL from environment (administrator-configured)
BACKEND_URL = os.environ.get("EXECUTION_BACKEND_URL", "")
BACKEND_TIMEOUT = float(os.environ.get("EXECUTION_BACKEND_TIMEOUT_SECONDS", "15.0"))

adapter = ExecutionAdapter(
    backend_url=BACKEND_URL if BACKEND_URL else None,
    timeout_seconds=BACKEND_TIMEOUT,
)

# Use the public low-level Server to register the Tool with the exact
# canonical inputSchema and outputSchema from the shared contract.
# This ensures schema hashes match without any private attribute access.
server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools():
    """Return the fixed run_code Tool with canonical schemas."""
    return [
        McpTool(
            name=TOOL_NAME,
            description=TOOL_DESCRIPTION,
            inputSchema=INPUT_SCHEMA,
            outputSchema=OUTPUT_SCHEMA,
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Dispatch run_code calls with proper error classification.

    Per correction 008 §2:
    - User program errors (compile_error, runtime_error, timed_out, etc.)
      return a normal RunCodeOutput — NOT a Tool error.
    - Infrastructure errors (backend unavailable, timeout, invalid result)
      return a Tool error (isError=true) with a stable sanitized code.
    - Invalid input contract returns a Tool error (isError=true) with
      code "invalid_input" — NOT a compile_error.
    """
    if name != TOOL_NAME:
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=_sanitize_error("invalid_input"),
            )],
        )

    # Validate input against the fixed contract
    try:
        inp = RunCodeInput.model_validate(arguments)
    except Exception as exc:
        # Invalid input contract → Tool error, NOT compile_error
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=_sanitize_error("invalid_input"),
            )],
        )

    # Execute via adapter — infrastructure errors are raised, not returned
    try:
        result = adapter.run_code(inp)
    except BackendUnavailableError:
        # Infrastructure failure → Tool error with stable code
        logger.warning("run_code backend unavailable")
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=_sanitize_error("backend_unavailable"),
            )],
        )
    except InvalidToolResultError:
        # Infrastructure failure → Tool error with stable code
        logger.warning("run_code backend returned an invalid result")
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=_sanitize_error("invalid_tool_result"),
            )],
        )

    # Successful execution — return RunCodeOutput as structured content
    # Per MCP protocol: when outputSchema is defined, the result must
    # include structuredContent for the client to validate against the schema.
    return CallToolResult(
        content=[TextContent(type="text", text=result.model_dump_json())],
        structuredContent=result.model_dump(),
    )


# ---------------------------------------------------------------------------
# Backend readiness endpoint (correction 005 §3.1 point 4)
# ---------------------------------------------------------------------------

async def _readyz_handler(scope, receive, send):
    """Internal health endpoint — NOT a Tool, NOT on the MCP protocol.

    Returns ``{ready: bool, reason_code: str}`` without exposing URLs,
    credentials, or remote body text. Only reports whether the
    execution backend URL is configured and reachable.
    """
    configured = adapter.backend_url is not None and len(adapter.backend_url) > 0
    if not configured:
        body = json.dumps({"ready": False, "reason_code": "backend_not_configured"}).encode()
    else:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.head(adapter.backend_url.rstrip("/"))
                backend_ok = 200 <= resp.status_code < 300
        except Exception:
            backend_ok = False
        if backend_ok:
            body = json.dumps({"ready": True, "reason_code": "ok"}).encode()
        else:
            body = json.dumps({"ready": False, "reason_code": "backend_unreachable"}).encode()

    await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"application/json"]]})
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# ASGI app — public Streamable HTTP transport + /readyz (correction 008 §3)
# ---------------------------------------------------------------------------

def create_app():
    """Create the Streamable HTTP ASGI application with /readyz support.

    Uses the public low-level Server + StreamableHTTPSessionManager +
    StreamableHTTPASGIApp — all public API, no private attributes.

    Handles the ASGI lifespan protocol to start/stop the session manager,
    which is required for the StreamableHTTPASGIApp to process requests.
    """
    session_manager = StreamableHTTPSessionManager(
        app=server,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    mcp_app = StreamableHTTPASGIApp(session_manager)
    session_manager_run = None

    async def combined_app(scope, receive, send):
        if scope["type"] == "lifespan":
            # Handle ASGI lifespan to start/stop the session manager.
            # Without this, the StreamableHTTPASGIApp raises
            # "Task group is not initialized" on first request.
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    try:
                        session_manager_run = session_manager.run()
                        await session_manager_run.__aenter__()
                    except Exception as exc:
                        await send({
                            "type": "lifespan.startup.failed",
                            "message": str(exc),
                        })
                        return
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    if session_manager_run is None:
                        await send({"type": "lifespan.shutdown.complete"})
                        return
                    try:
                        await session_manager_run.__aexit__(None, None, None)
                    except Exception as exc:
                        await send({
                            "type": "lifespan.shutdown.failed",
                            "message": str(exc),
                        })
                        return
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http" and scope.get("path") == "/readyz":
            await _readyz_handler(scope, receive, send)
            return
        else:
            await mcp_app(scope, receive, send)

    return combined_app


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MCP_EXECUTION_PORT", "8100"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)

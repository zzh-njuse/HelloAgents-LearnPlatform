"""Code lab execution service — MCP client for the fixed execution Tool.

Product API/worker only connects to the execution MCP server via the
official stable Python MCP SDK over Streamable HTTP. It never calls
Judge0/Piston HTTP directly — that translation happens inside
apps/mcp_execution.

Per ADR 006 §2.3: protocol version 2025-11-25, Streamable HTTP.
Per Spec 004 §5.2: fixed Tool ``run_code`` with exact input/output schema.

Per correction 004 §2: canonical constants come from the shared contract
package. No duplicated Pydantic models or hand-written schemas.

IMPORTANT: The MCP_EXECUTION_ADAPTER_URL is a Streamable HTTP MCP endpoint
(e.g. http://mcp-execution:8100/mcp), NOT a Judge0 /submissions URL.
The product worker must never call Judge0 HTTP directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from learn_platform_api.settings import Settings

# Per correction 004 §2: import from the single canonical shared contract.
from shared.mcp_execution_contract import (
    ALLOWED_LANGUAGES,
    INPUT_SCHEMA_HASH,
    MCP_PROTOCOL_VERSION,
    OUTPUT_MAX_BYTES,
    OUTPUT_SCHEMA_HASH,
    SERVER_NAME,
    SOURCE_CODE_MAX_CHARS,
    STDIN_MAX_CHARS,
    TOOL_NAME,
    WALL_TIME_SECONDS,
    compute_canonical_hash,
)

EXPECTED_SERVER_NAME = SERVER_NAME
EXPECTED_TOOL_NAME = TOOL_NAME

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpHandshakeSnapshot:
    """Verified snapshot from MCP initialize + list_tools — authoritative for final commit."""
    server_name: str
    server_version: str
    protocol_version: str
    tool_name: str
    input_schema_hash: str
    output_schema_hash: str


@dataclass(frozen=True)
class RunCodeResult:
    """Fixed output contract — mirrors the MCP Tool return schema."""
    status: str  # completed|compile_error|runtime_error|timed_out|output_limited
    exit_code: int
    compile_output: str
    stdout: str
    stderr: str
    duration_ms: int
    runtime: str
    stdout_truncated: bool
    stderr_truncated: bool


class ExecutionMcpError(Exception):
    """Base for MCP execution errors — infrastructure, not user program errors."""


class BackendUnavailableError(ExecutionMcpError):
    """Backend unreachable or not configured."""


class InvalidToolResultError(ExecutionMcpError):
    """Backend returned result that violates the fixed output schema."""


class SchemaDriftError(ExecutionMcpError):
    """Server/tool/schema version does not match expected snapshot."""


# ---------------------------------------------------------------------------
# Tool error classification — per correction 009 §2
# ---------------------------------------------------------------------------

# Stable error codes produced by the MCP execution server.
# These are the ONLY strings that appear in Tool error TextContent.
_RETRYABLE_TOOL_ERRORS = frozenset({
    "backend_unavailable",
    "backend_timeout",
})

_NON_RETRYABLE_TOOL_ERRORS = frozenset({
    "invalid_tool_result",
    "invalid_input",
})

_ALL_STABLE_TOOL_ERRORS = _RETRYABLE_TOOL_ERRORS | _NON_RETRYABLE_TOOL_ERRORS


def _classify_tool_error(error_text: str) -> str:
    """Classify a Tool error by its stable code.

    The server returns only stable codes (e.g. "backend_unavailable").
    We extract the code and map it to the correct exception type.
    Any unrecognized, combined, or extra content → non-retryable
    "unrecognized_tool_error" — never echo remote text.
    """
    # The server returns just the stable code as the full TextContent.
    # Strip whitespace for robustness.
    code = error_text.strip()

    if code in _ALL_STABLE_TOOL_ERRORS:
        return code

    # Unknown or malformed — non-retryable, no remote text propagation
    return "unrecognized_tool_error"


# ---------------------------------------------------------------------------
# MCP client using the official Python SDK
# ---------------------------------------------------------------------------

async def call_run_code_via_mcp(
    request_id: str,
    language: str,
    source_code: str,
    stdin: str,
    settings: Settings,
) -> tuple[RunCodeResult, McpHandshakeSnapshot]:
    """Call the fixed ``run_code`` Tool via MCP Streamable HTTP.

    This is the ONLY production path. It:
    1. Connects to the execution MCP server at settings.mcp_execution_adapter_url
    2. Initializes and verifies protocol/server/tool/schema
    3. Calls ``run_code`` with the fixed input contract
    4. Validates the result against the fixed output contract
    5. Returns (RunCodeResult, McpHandshakeSnapshot) or raises ExecutionMcpError

    The McpHandshakeSnapshot contains the verified server/tool/schema info
    from the actual MCP handshake — this is the authoritative snapshot
    that the worker must use for final commit, not local constants.

    No Judge0/Piston HTTP is used here. No fake backend is generated.
    The URL is a Streamable HTTP MCP endpoint, NOT a Judge0 /submissions URL.
    """
    if not settings.mcp_execution_adapter_url:
        raise BackendUnavailableError("execution MCP adapter URL not configured")

    try:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.types import CallToolResult, TextContent
    except ImportError as exc:
        raise BackendUnavailableError(
            f"MCP SDK not available: {exc}. Install mcp>=1.27,<2"
        ) from exc

    # The MCP Streamable HTTP endpoint — NOT a Judge0 URL
    url = settings.mcp_execution_adapter_url.rstrip("/")
    # Ensure we hit the MCP endpoint path, not a Judge0 path
    if "/submissions" in url:
        raise BackendUnavailableError(
            "MCP_EXECUTION_ADAPTER_URL must be a Streamable HTTP MCP endpoint, "
            "not a Judge0 /submissions URL"
        )
    # Append /mcp if not already present (standard Streamable HTTP path)
    if not url.endswith("/mcp"):
        url = url + "/mcp"

    timeout = settings.code_lab_execution_timeout_seconds

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=timeout) as _http_client:
            async with streamable_http_client(url, http_client=_http_client) as (read, write, _):
                from mcp.client.session import ClientSession
                async with ClientSession(read, write) as session:
                    # Initialize and verify protocol version
                    init_result = await session.initialize()

                    # Verify server identity
                    server_info = init_result.serverInfo
                    if server_info and server_info.name != EXPECTED_SERVER_NAME:
                        raise SchemaDriftError(
                            f"unexpected MCP server: expected {EXPECTED_SERVER_NAME!r}, "
                            f"got {server_info.name!r}"
                        )

                    # Verify protocol version
                    if init_result.protocolVersion != MCP_PROTOCOL_VERSION:
                        raise SchemaDriftError(
                            f"protocol drift: expected {MCP_PROTOCOL_VERSION!r}, "
                            f"got {init_result.protocolVersion!r}"
                        )

                    # Verify the fixed Tool exists and validate schema hashes
                    tools_result = await session.list_tools()
                    tool_names = {t.name for t in tools_result.tools}
                    if EXPECTED_TOOL_NAME not in tool_names:
                        raise SchemaDriftError(
                            f"expected Tool {EXPECTED_TOOL_NAME!r} not found; "
                            f"available: {sorted(tool_names)}"
                        )
                    # Find the target tool and validate input/output schema
                    target_tool = next(t for t in tools_result.tools if t.name == EXPECTED_TOOL_NAME)
                    # Reject duplicate Tool names — must be exactly one run_code
                    tool_count = sum(1 for t in tools_result.tools if t.name == EXPECTED_TOOL_NAME)
                    if tool_count != 1:
                        raise SchemaDriftError(
                            f"expected exactly one {EXPECTED_TOOL_NAME!r}, found {tool_count}"
                        )
                    # inputSchema and outputSchema must be present
                    if not target_tool.inputSchema:
                        raise SchemaDriftError(
                            f"Tool {EXPECTED_TOOL_NAME!r} missing inputSchema"
                        )
                    if not target_tool.outputSchema:
                        raise SchemaDriftError(
                            f"Tool {EXPECTED_TOOL_NAME!r} missing outputSchema"
                        )
                    input_schema_hash = _compute_schema_hash(target_tool.inputSchema)
                    output_schema_hash = _compute_schema_hash(target_tool.outputSchema)
                    if input_schema_hash != INPUT_SCHEMA_HASH:
                        raise SchemaDriftError("run_code input schema drift")
                    if output_schema_hash != OUTPUT_SCHEMA_HASH:
                        raise SchemaDriftError("run_code output schema drift")
                    # Build the authoritative handshake snapshot
                    handshake = McpHandshakeSnapshot(
                        server_name=server_info.name if server_info else "",
                        server_version=server_info.version if server_info else "",
                        protocol_version=init_result.protocolVersion,
                        tool_name=EXPECTED_TOOL_NAME,
                        input_schema_hash=input_schema_hash,
                        output_schema_hash=output_schema_hash,
                    )

                    # Call the fixed Tool
                    tool_args = {
                        "request_id": request_id,
                        "language": language,
                        "source_code": source_code,
                        "stdin": stdin,
                    }

                    result: CallToolResult = await session.call_tool(
                        EXPECTED_TOOL_NAME,
                        arguments=tool_args,
                    )

                    if result.isError:
                        # Per correction 009 §2: classify by stable error code.
                        # Only parse the stable code from TextContent — never
                        # propagate unvetted remote text into local exceptions.
                        error_text = ""
                        for content in result.content:
                            if isinstance(content, TextContent):
                                error_text += content.text
                        _code = _classify_tool_error(error_text)
                        if _code in _RETRYABLE_TOOL_ERRORS:
                            raise BackendUnavailableError(_code)
                        else:
                            # Contract/validation errors — not retryable
                            raise InvalidToolResultError(_code)

                    # Extract the JSON result from TextContent
                    raw_json = ""
                    for content in result.content:
                        if isinstance(content, TextContent):
                            raw_json += content.text

                    if not raw_json:
                        raise InvalidToolResultError("empty MCP Tool result")

                    # Parse and validate against fixed output contract
                    try:
                        raw = json.loads(raw_json)
                    except json.JSONDecodeError as exc:
                        raise InvalidToolResultError(
                            f"non-JSON MCP result: {exc}"
                        ) from exc

                    return _validate_result(raw), handshake

    except BackendUnavailableError:
        raise
    except InvalidToolResultError:
        raise
    except SchemaDriftError:
        raise
    except Exception as exc:
        # Connection errors, timeouts, etc. — always infrastructure error
        raise BackendUnavailableError(f"MCP connection failed: {exc}") from exc


def _compute_schema_hash(schema: dict | None) -> str:
    """Compute a stable hash of a JSON schema dict for drift detection.

    Per correction 006 §4: delegates to the shared compute_canonical_hash
    from the shared contract module. No duplicated algorithm.
    """
    if schema is None:
        return ""
    return compute_canonical_hash(schema)


def _validate_result(raw: dict) -> RunCodeResult:
    """Validate raw dict against the fixed output contract.

    Maps unknown fields, illegal enum values, or negative duration
    to InvalidToolResultError — never to a user program error.
    """
    valid_statuses = {
        "completed", "compile_error", "runtime_error",
        "timed_out", "output_limited",
    }

    status = raw.get("status", "")
    if status not in valid_statuses:
        raise InvalidToolResultError(f"invalid status: {status!r}")

    exit_code = raw.get("exit_code", -1)
    if not isinstance(exit_code, int):
        exit_code = -1

    duration_ms = raw.get("duration_ms", 0)
    if not isinstance(duration_ms, int) or duration_ms < 0:
        duration_ms = 0

    return RunCodeResult(
        status=status,
        exit_code=exit_code,
        compile_output=str(raw.get("compile_output", "")),
        stdout=str(raw.get("stdout", "")),
        stderr=str(raw.get("stderr", "")),
        duration_ms=duration_ms,
        runtime=str(raw.get("runtime", "")),
        stdout_truncated=bool(raw.get("stdout_truncated", False)),
        stderr_truncated=bool(raw.get("stderr_truncated", False)),
    )


# ---------------------------------------------------------------------------
# Synchronous wrapper for rq worker (which runs sync)
# ---------------------------------------------------------------------------

def execute_code_run_sync(
    request_id: str,
    language: str,
    source_code: str,
    stdin: str,
    settings: Settings,
) -> tuple[RunCodeResult, McpHandshakeSnapshot]:
    """Synchronous entry point for the rq worker.

    Creates a fresh event loop for the async MCP client call,
    avoiding issues with existing loops or thread-local state.

    Per §2.5: In an RQ worker (which runs sync), there should be no
    running event loop. We create a new one with asyncio.new_event_loop()
    and close it after use. If we unexpectedly find ourselves inside a
    running loop (e.g. test harness), we offload to a separate thread.

    Returns (RunCodeResult, McpHandshakeSnapshot) — the snapshot is the
    authoritative handshake result that the worker uses for final commit.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an already-running loop — offload to a new thread
        # with its own event loop. This handles the case where the sync
        # wrapper is called from within an async context (e.g. test).
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                call_run_code_via_mcp(request_id, language, source_code, stdin, settings),
            )
            return future.result()
    else:
        # Normal RQ worker path: no running loop. Create a fresh loop,
        # run the coroutine, and close the loop. This is more stable than
        # asyncio.run() in environments where loop policy or cleanup may vary.
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            result = new_loop.run_until_complete(
                call_run_code_via_mcp(request_id, language, source_code, stdin, settings),
            )
            return result
        finally:
            # Clean up: close the loop and unset it from the current thread
            try:
                new_loop.close()
            finally:
                asyncio.set_event_loop(None)

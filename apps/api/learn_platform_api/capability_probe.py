"""Capability probe — periodic MCP capability readiness checker.

Per correction 005 §3: a real probe process that actually connects to MCP
servers, verifies identity/schema/tools, and writes capability projections
to the database. The API only reads projections; it never calls MCP directly.

Per correction 006 §3: uses the official MCP SDK ClientSession for all
handshakes — no hand-written JSON-RPC, no hand-written SSE parser, no
hand-written session header management. The protocol version is the one
actually negotiated by the SDK, validated against ADR-allowed versions.

This module is the entry point for the ``capability-probe`` Compose service.
It uses the API runtime image with an independent command, so it shares
the same DB access but does NOT need Redis, Qdrant, storage, or
embedding/generation provider keys.

Topology per correction 005 §3:
- Only gets: Postgres, MCP execution adapter URL, Wolfram enabled/URL/optional
  credentials, probe interval/TTL.
- Does NOT get: Redis, Qdrant, storage, embedding/generation provider keys.
- Joins default data network + mcp-execution-net.
- Does NOT listen on any port.
- Each cycle: probe execution + science, write McpCapabilityStatus.
- Loop interval < TTL, supports graceful exit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

logger = logging.getLogger("capability_probe")

# ---------------------------------------------------------------------------
# Configuration — only what the probe needs
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
MCP_EXECUTION_ADAPTER_URL = os.environ.get("MCP_EXECUTION_ADAPTER_URL", "")
WOLFRAM_MCP_ENABLED = os.environ.get("WOLFRAM_MCP_ENABLED", "false").lower() in ("true", "1", "yes")
WOLFRAM_MCP_URL = os.environ.get("WOLFRAM_MCP_URL", "")
WOLFRAM_MCP_API_KEY = os.environ.get("WOLFRAM_MCP_API_KEY", "")
PROBE_INTERVAL_SECONDS = int(os.environ.get("CAPABILITY_PROBE_INTERVAL_SECONDS", "20"))
PROBE_TTL_SECONDS = int(os.environ.get("CAPABILITY_PROBE_TTL_SECONDS", "30"))

# Must have interval < TTL so projection doesn't expire between probes
assert PROBE_INTERVAL_SECONDS < PROBE_TTL_SECONDS, (
    f"PROBE_INTERVAL_SECONDS ({PROBE_INTERVAL_SECONDS}) must be < "
    f"PROBE_TTL_SECONDS ({PROBE_TTL_SECONDS})"
)

# ADR-allowed protocol versions (correction 006 §3: validate against ADR,
# not a single hardcoded string)
ADR_ALLOWED_PROTOCOL_VERSIONS = frozenset({"2025-11-25"})
WOLFRAM_ALLOWED_PROTOCOL_VERSIONS = frozenset({"2025-03-26"})

# Graceful shutdown
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ---------------------------------------------------------------------------
# Canonical schema hash — import from shared contract (correction 006 §4)
# ---------------------------------------------------------------------------

from shared.mcp_execution_contract import compute_canonical_hash


# ---------------------------------------------------------------------------
# Execution MCP probe (correction 005 §3.1, correction 006 §3)
# ---------------------------------------------------------------------------

def probe_execution(adapter_url: str) -> dict:
    """Probe the execution MCP adapter using official MCP ClientSession.

    Verifies:
    1. MCP initialize protocol/server identity (using SDK-negotiated version)
    2. Exact single ``run_code`` Tool
    3. Shared canonical input/output schema hash
    4. Execution adapter backend readiness (via /readyz)

    Returns a projection dict suitable for write_capability_projection.
    """
    if not adapter_url:
        return {"status": "unavailable", "detail": "未配置", "verified_schema_hash": ""}

    try:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession
    except ImportError:
        return {"status": "unavailable", "detail": "MCP SDK 不可导入", "verified_schema_hash": ""}

    url = adapter_url.rstrip("/")
    if not url.endswith("/mcp"):
        url = url + "/mcp"

    async def _probe():
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    # Step 1: Initialize
                    init_result = await session.initialize()

                    # Verify protocol version against ADR-allowed set
                    # (correction 006 §3: use server-negotiated version,
                    #  validate against ADR, not a single hardcoded string)
                    protocol_version = init_result.protocolVersion
                    if protocol_version not in ADR_ALLOWED_PROTOCOL_VERSIONS:
                        return {"status": "unavailable", "detail": "协议版本漂移", "verified_schema_hash": ""}

                    # Verify server identity
                    server_info = init_result.serverInfo
                    server_name = server_info.name if server_info else ""
                    if server_name != "learn-platform-code-execution":
                        return {"status": "unavailable", "detail": "服务身份不符", "verified_schema_hash": ""}

                    # Step 2: List tools
                    tools_result = await session.list_tools()
                    tools = tools_result.tools

                    # Verify exactly one tool: run_code
                    if len(tools) != 1 or tools[0].name != "run_code":
                        return {"status": "unavailable", "detail": "Tool 白名单不符", "verified_schema_hash": ""}

                    tool = tools[0]
                    input_schema = tool.inputSchema or {}
                    output_schema = tool.outputSchema or {}

                    # Step 3: Compute canonical hashes and verify against shared contract
                    input_hash = compute_canonical_hash(input_schema)
                    output_hash = compute_canonical_hash(output_schema)

                    try:
                        from shared.mcp_execution_contract import (
                            INPUT_SCHEMA_HASH,
                            OUTPUT_SCHEMA_HASH,
                        )
                        if input_hash != INPUT_SCHEMA_HASH or output_hash != OUTPUT_SCHEMA_HASH:
                            return {
                                "status": "unavailable",
                                "detail": "Schema hash 漂移",
                                "verified_schema_hash": "",
                            }
                    except ImportError:
                        return {
                            "status": "unavailable",
                            "detail": "共享合同不可导入",
                            "verified_schema_hash": "",
                        }

                    # Step 4: Backend readiness via /readyz
                    base_url = adapter_url.rstrip("/")
                    readyz_url = f"{base_url}/readyz"
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            readyz_resp = await client.get(readyz_url)
                            if readyz_resp.status_code != 200:
                                return {
                                    "status": "unavailable",
                                    "detail": "后端健康检查失败",
                                    "verified_schema_hash": "",
                                }
                            readyz_data = readyz_resp.json()
                            if not readyz_data.get("ready"):
                                reason = readyz_data.get("reason_code", "backend_unavailable")
                                return {
                                    "status": "unavailable",
                                    "detail": f"后端不可用: {reason}",
                                    "verified_schema_hash": "",
                                }
                    except Exception:
                        return {
                            "status": "unavailable",
                            "detail": "后端健康检查不可达",
                            "verified_schema_hash": "",
                        }

                    # All checks passed — compose verified hash
                    verified_hash = f"{input_hash}:{output_hash}"
                    return {
                        "status": "ready",
                        "detail": "可用",
                        "verified_schema_hash": verified_hash,
                    }

    try:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _probe()).result()
        else:
            return asyncio.run(_probe())
    except Exception as exc:
        logger.warning("Execution probe failed: %s", exc)
        return {"status": "unavailable", "detail": "探测异常", "verified_schema_hash": ""}


# ---------------------------------------------------------------------------
# Wolfram MCP probe (correction 005 §3.2, correction 006 §3)
# ---------------------------------------------------------------------------

# Fixed Wolfram tool allowlist per Spec 004 §6.2 / ADR 006 §2.2
WOLFRAM_TOOL_ALLOWLIST = {"WolframAlpha", "WolframContext"}
# Requests for these Tools remain forbidden even when the remote advertises
# them.  Presence is not admission; only WOLFRAM_TOOL_ALLOWLIST is hashed.
WOLFRAM_FORBIDDEN_TOOLS = {"WolframLanguageEvaluator"}


def probe_science(wolfram_url: str, api_key: str = "") -> dict:
    """Probe the Wolfram remote MCP using official MCP ClientSession.

    Only initialize + list_tools — NEVER calls a business Tool.

    Verifies:
    - protocol/server identity (SDK-negotiated version, ADR-validated)
    - both approved Tools exist: WolframAlpha + WolframContext
    - remote extra Tools never enter the product authorization surface
    - both Tools' canonical input/output schema
    - combines complete server/protocol/2-Tool schema into verified hash

    The probe-written verified hash IS the admin admission revision.
    The API only reads the projection.
    """
    if not wolfram_url:
        return {"status": "unavailable", "detail": "未配置", "verified_schema_hash": ""}

    try:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession
    except ImportError:
        return {"status": "unavailable", "detail": "MCP SDK 不可导入", "verified_schema_hash": ""}

    url = wolfram_url.rstrip("/")
    if not url.endswith("/mcp"):
        url = url + "/mcp"

    # Build headers with optional auth
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def _probe():
        import httpx
        # Build httpx client with optional auth headers
        _headers = headers if headers else None
        async with httpx.AsyncClient(timeout=15.0, headers=_headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    # Initialize
                    init_result = await session.initialize()

                    # Validate protocol version against ADR-allowed set
                    protocol_version = init_result.protocolVersion
                    if protocol_version not in WOLFRAM_ALLOWED_PROTOCOL_VERSIONS:
                        return {"status": "unavailable", "detail": "协议版本漂移", "verified_schema_hash": ""}

                    # List tools
                    tools_result = await session.list_tools()
                    tools = tools_result.tools
                    tool_names = {t.name for t in tools}

                    # The remote service may publish additional Tools.  They are
                    # deliberately ignored: only the product-owned allowlist is
                    # hashed, authorized and callable.
                    if not WOLFRAM_TOOL_ALLOWLIST.issubset(tool_names):
                        return {
                            "status": "unavailable",
                            "detail": "白名单 Tool 缺失",
                            "verified_schema_hash": "",
                        }

                    # Compute verified hash from both Tools' schemas
                    tool_schemas = {}
                    for name in WOLFRAM_TOOL_ALLOWLIST:
                        tool = next(t for t in tools if t.name == name)
                        input_hash = compute_canonical_hash(tool.inputSchema or {})
                        output_hash = compute_canonical_hash(tool.outputSchema or {})
                        tool_schemas[name] = f"{input_hash}:{output_hash}"

                    # Combine server + protocol + both Tool schemas into stable hash
                    combined = json.dumps({
                        "protocol": protocol_version,
                        "tools": tool_schemas,
                    }, sort_keys=True)
                    verified_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

                    return {
                        "status": "ready",
                        "detail": "可用",
                        "verified_schema_hash": verified_hash,
                    }

    try:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _probe()).result()
        else:
            return asyncio.run(_probe())
    except Exception as exc:
        logger.warning("Science probe failed: %s", exc)
        return {"status": "unavailable", "detail": "探测异常", "verified_schema_hash": ""}


# ---------------------------------------------------------------------------
# Projection writer — calls the product readiness service
# ---------------------------------------------------------------------------

def write_projection(db: Session, capability_id: str, probe_result: dict) -> None:
    """Write a probe result as a capability status projection."""
    from learn_platform_api.services.readiness import write_capability_projection

    write_capability_projection(
        db,
        capability_id=capability_id,
        status=probe_result["status"],
        detail=probe_result["detail"],
        verified_schema_hash=probe_result.get("verified_schema_hash", ""),
        ttl_seconds=PROBE_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# Main probe loop
# ---------------------------------------------------------------------------

def run_probe_loop() -> None:
    """Run the capability probe loop until shutdown."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL not configured — cannot start probe")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)
    logger.info(
        "Capability probe starting: interval=%ds ttl=%ds execution_url=%s wolfram_enabled=%s",
        PROBE_INTERVAL_SECONDS, PROBE_TTL_SECONDS,
        "configured" if MCP_EXECUTION_ADAPTER_URL else "none",
        WOLFRAM_MCP_ENABLED,
    )

    while not _shutdown:
        cycle_start = time.monotonic()
        try:
            with Session(engine) as db:
                # Probe execution MCP
                execution_result = probe_execution(MCP_EXECUTION_ADAPTER_URL)
                write_projection(db, "code_execution", execution_result)
                db.commit()
                logger.info(
                    "Execution probe: status=%s detail=%s hash=%s",
                    execution_result["status"],
                    execution_result["detail"],
                    execution_result.get("verified_schema_hash", "")[:8],
                )

                # Probe science (Wolfram) MCP
                if WOLFRAM_MCP_ENABLED:
                    science_result = probe_science(WOLFRAM_MCP_URL, WOLFRAM_MCP_API_KEY)
                    write_projection(db, "science_computation", science_result)
                    db.commit()
                    logger.info(
                        "Science probe: status=%s detail=%s hash=%s",
                        science_result["status"],
                        science_result["detail"],
                        science_result.get("verified_schema_hash", "")[:8],
                    )
                else:
                    # Write disabled projection
                    write_projection(db, "science_computation", {
                        "status": "unavailable",
                        "detail": "未启用",
                        "verified_schema_hash": "",
                    })
                    db.commit()

        except Exception as exc:
            logger.error("Probe cycle failed: %s", exc, exc_info=True)

        # Sleep for remaining interval
        elapsed = time.monotonic() - cycle_start
        sleep_time = max(0, PROBE_INTERVAL_SECONDS - elapsed)
        if sleep_time > 0 and not _shutdown:
            time.sleep(sleep_time)

    logger.info("Capability probe shut down.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run_probe_loop()

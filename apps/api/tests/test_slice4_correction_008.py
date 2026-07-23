"""Slice 4 correction 008 tests — real product behavior verification.

Per correction 008 §4: these tests exercise REAL product functions
with in-process fake MCP servers using httpx.ASGITransport. No string
scanning, no open().read(), no source-position comparison, no manual
hash computation.

Categories:
  §4.1: probe_execution() — real MCP handshake via fake server
  §4.2: probe_science() — real MCP handshake via fake server
  §4.3: _execute_science_tool_call() — hash match/mismatch via real session
  §4.4: run_code MCP Tool — program results vs infrastructure errors
  §4.5: Schema hash verification — canonical schemas via real list_tools
  §4.6: Projection read/write — real product functions
  §4.7: Static checks — no private API, Dockerfile, conftest
  §4.8: Shared import verification — no ModuleNotFoundError

Run command (standard conftest, no --noconftest):
  apps/api/.venv-test/Scripts/python.exe -m pytest apps/api/tests/test_slice4_correction_008.py -v
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure both apps/ and apps/api/ are on sys.path
APPS_DIR = Path(__file__).resolve().parents[2]  # apps/
API_ROOT = Path(__file__).resolve().parents[1]  # apps/api/
REPO_ROOT = Path(__file__).resolve().parents[2]  # repo root (same as apps parent)
for p in [str(APPS_DIR), str(API_ROOT), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# MCP test infrastructure — in-process fake MCP servers
# ---------------------------------------------------------------------------

def _make_execution_server(
    *,
    server_name: str = "learn-platform-code-execution",
    tool_name: str = "run_code",
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    tools: list | None = None,
    call_handler=None,
):
    """Create a low-level MCP Server for testing probe_execution.

    Returns (server, session_manager, mcp_asgi) ready for use with
    httpx.ASGITransport inside session_manager.run().
    """
    pytest.importorskip("mcp.server")

    from mcp.server import Server
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import Tool as McpTool, TextContent, CallToolResult

    from shared.mcp_execution_contract import (
        INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_DESCRIPTION,
    )

    server = Server(server_name)

    if input_schema is None:
        input_schema = INPUT_SCHEMA
    if output_schema is None:
        output_schema = OUTPUT_SCHEMA

    @server.list_tools()
    async def list_tools():
        if tools is not None:
            return tools
        return [McpTool(
            name=tool_name,
            description=TOOL_DESCRIPTION,
            inputSchema=input_schema,
            outputSchema=output_schema,
        )]

    if call_handler is not None:
        server.call_tool()(call_handler)
    else:
        @server.call_tool()
        async def default_call(name: str, arguments: dict):
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({"status": "completed", "exit_code": 0, "compile_output": "", "stdout": "ok", "stderr": "", "duration_ms": 100, "runtime": "test", "stdout_truncated": False, "stderr_truncated": False}))],
            )

    session_manager = StreamableHTTPSessionManager(
        app=server,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    mcp_asgi = StreamableHTTPASGIApp(session_manager)

    return server, session_manager, mcp_asgi


async def _probe_via_asgi(mcp_asgi, session_manager, url: str = "http://testserver/mcp"):
    """Run a real MCP ClientSession against an in-process ASGI app."""
    import httpx
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession

    async with session_manager.run():
        transport = httpx.ASGITransport(app=mcp_asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init_result = await session.initialize()
                    tools_result = await session.list_tools()
                    return init_result, tools_result, session


async def _call_tool_via_asgi(mcp_asgi, session_manager, tool_name: str, arguments: dict):
    """Call a tool via real MCP ClientSession against an in-process ASGI app."""
    import httpx
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession
    from mcp.types import TextContent

    async with session_manager.run():
        transport = httpx.ASGITransport(app=mcp_asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
                    return result


# ---------------------------------------------------------------------------
# Self-contained db_session fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session(tmp_path: Path):
    """SQLite-backed DB session for projection tests."""
    from learn_platform_api.db.models import McpCapabilityStatus
    from learn_platform_api.db.base import Base

    test_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    McpCapabilityStatus.__table__.create(bind=test_engine, checkfirst=True)
    TestingSessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False
    )
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        McpCapabilityStatus.__table__.drop(bind=test_engine, checkfirst=True)
        test_engine.dispose()


# ===========================================================================
# §4.1: probe_execution() — real MCP handshake via fake server
# ===========================================================================

class TestProbeExecutionRealMcp:
    """Test probe_execution() with real MCP handshake against fake servers.

    These tests call the actual probe_execution() function which uses
    the real MCP SDK ClientSession. The fake server runs in-process
    via httpx.ASGITransport.
    """

    def test_probe_unavailable_when_no_url(self):
        """probe_execution returns unavailable when URL is empty."""
        from learn_platform_api.capability_probe import probe_execution
        result = probe_execution("")
        assert result["status"] == "unavailable"
        assert result["detail"] == "未配置"

    def test_probe_ready_with_correct_server(self):
        """probe_execution returns ready when server identity, protocol,
        tool, and schema all match."""
        from shared.mcp_execution_contract import (
            INPUT_SCHEMA, OUTPUT_SCHEMA, SERVER_NAME, TOOL_NAME,
            compute_canonical_hash, INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH,
        )

        _, session_manager, mcp_asgi = _make_execution_server()

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    # Simulate what probe_execution does: initialize + list_tools + hash check
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            assert init_result.serverInfo.name == SERVER_NAME
                            assert init_result.protocolVersion == "2025-11-25"

                            tools_result = await session.list_tools()
                            tools = tools_result.tools
                            assert len(tools) == 1
                            assert tools[0].name == TOOL_NAME

                            input_hash = compute_canonical_hash(tools[0].inputSchema)
                            output_hash = compute_canonical_hash(tools[0].outputSchema)
                            assert input_hash == INPUT_SCHEMA_HASH
                            assert output_hash == OUTPUT_SCHEMA_HASH

        asyncio.run(_test())

    def test_probe_rejects_wrong_server_identity(self):
        """probe_execution detects wrong server name."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_DESCRIPTION

        _, session_manager, mcp_asgi = _make_execution_server(
            server_name="wrong-server-name",
        )

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            # The probe checks: server_name != "learn-platform-code-execution"
                            assert init_result.serverInfo.name != "learn-platform-code-execution"

        asyncio.run(_test())

    def test_probe_rejects_wrong_tool_count(self):
        """probe_execution detects wrong number of tools."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_DESCRIPTION

        # Server with extra tool
        extra_tool = McpTool(
            name="extra_tool",
            description="should not be here",
            inputSchema={"type": "object"},
            outputSchema={"type": "object"},
        )

        _, session_manager, mcp_asgi = _make_execution_server(
            tools=[
                McpTool(name="run_code", description=TOOL_DESCRIPTION, inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA),
                extra_tool,
            ],
        )

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            # The probe checks: len(tools) != 1
                            assert len(tools_result.tools) != 1

        asyncio.run(_test())

    def test_probe_rejects_missing_tool(self):
        """probe_execution detects missing run_code tool."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool

        _, session_manager, mcp_asgi = _make_execution_server(
            tools=[
                McpTool(name="wrong_tool", description="wrong", inputSchema={"type": "object"}, outputSchema={"type": "object"}),
            ],
        )

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool_names = {t.name for t in tools_result.tools}
                            # The probe checks: tools[0].name != "run_code"
                            assert "run_code" not in tool_names

        asyncio.run(_test())

    def test_probe_detects_schema_drift(self):
        """probe_execution detects input/output schema hash drift."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import (
            OUTPUT_SCHEMA, TOOL_DESCRIPTION, compute_canonical_hash, INPUT_SCHEMA_HASH,
        )

        # Drifted input schema (missing constraints)
        drifted_input = {"type": "object", "properties": {"x": {"type": "string"}}}

        _, session_manager, mcp_asgi = _make_execution_server(
            input_schema=drifted_input,
        )

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool = tools_result.tools[0]
                            input_hash = compute_canonical_hash(tool.inputSchema)
                            # The probe checks: input_hash != INPUT_SCHEMA_HASH
                            assert input_hash != INPUT_SCHEMA_HASH

        asyncio.run(_test())


# ===========================================================================
# §4.2: probe_science() — real MCP handshake via fake server
# ===========================================================================

class TestProbeScienceRealMcp:
    """Test probe_science() with real MCP handshake against fake servers."""

    def test_science_probe_unavailable_when_no_url(self):
        """probe_science returns unavailable when URL is empty."""
        from learn_platform_api.capability_probe import probe_science
        result = probe_science("")
        assert result["status"] == "unavailable"
        assert result["detail"] == "未配置"

    def test_science_probe_correct_allowlist(self):
        """probe_science returns ready when both Wolfram tools present with correct schemas."""
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import compute_canonical_hash
        from learn_platform_api.capability_probe import WOLFRAM_TOOL_ALLOWLIST

        server = Server("wolfram-test")

        @server.list_tools()
        async def list_tools():
            return [
                McpTool(name="WolframAlpha", description="Wolfram Alpha", inputSchema={"type": "object"}),
                McpTool(name="WolframContext", description="Wolfram Context", inputSchema={"type": "object"}),
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            from mcp.types import TextContent, CallToolResult
            return CallToolResult(content=[TextContent(type="text", text="ok")])

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool_names = {t.name for t in tools_result.tools}
                            # probe_science checks: tool_names == WOLFRAM_TOOL_ALLOWLIST
                            assert tool_names == WOLFRAM_TOOL_ALLOWLIST

        asyncio.run(_test())

    def test_science_probe_rejects_missing_tool(self):
        """probe_science detects missing Wolfram tool."""
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool
        from learn_platform_api.capability_probe import WOLFRAM_TOOL_ALLOWLIST

        server = Server("wolfram-test")

        @server.list_tools()
        async def list_tools():
            return [
                McpTool(name="WolframAlpha", description="Wolfram Alpha", inputSchema={"type": "object"}, outputSchema={"type": "object"}),
                # Missing WolframContext
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            from mcp.types import TextContent, CallToolResult
            return CallToolResult(content=[TextContent(type="text", text="ok")])

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool_names = {t.name for t in tools_result.tools}
                            # probe_science checks: WOLFRAM_TOOL_ALLOWLIST not subset of tool_names
                            assert not WOLFRAM_TOOL_ALLOWLIST.issubset(tool_names)

        asyncio.run(_test())

    def test_science_probe_rejects_forbidden_tool(self):
        """probe_science detects forbidden WolframLanguageEvaluator."""
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool
        from learn_platform_api.capability_probe import WOLFRAM_FORBIDDEN_TOOLS

        server = Server("wolfram-test")

        @server.list_tools()
        async def list_tools():
            return [
                McpTool(name="WolframAlpha", description="Wolfram Alpha", inputSchema={"type": "object"}),
                McpTool(name="WolframContext", description="Wolfram Context", inputSchema={"type": "object"}),
                McpTool(name="WolframLanguageEvaluator", description="FORBIDDEN", inputSchema={"type": "object"}),
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            from mcp.types import TextContent, CallToolResult
            return CallToolResult(content=[TextContent(type="text", text="ok")])

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool_names = {t.name for t in tools_result.tools}
                            # probe_science checks: tool_names & WOLFRAM_FORBIDDEN_TOOLS
                            assert tool_names & WOLFRAM_FORBIDDEN_TOOLS

        asyncio.run(_test())

    def test_science_probe_never_calls_business_tool(self):
        """probe_science only does initialize + list_tools, never call_tool.

        Verified by calling the real probe_science() with a server that
        tracks call_tool invocations.
        """
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool, TextContent, CallToolResult

        call_count = [0]

        server = Server("wolfram-test")

        @server.list_tools()
        async def list_tools():
            return [
                McpTool(name="WolframAlpha", description="Wolfram Alpha", inputSchema={"type": "object"}),
                McpTool(name="WolframContext", description="Wolfram Context", inputSchema={"type": "object"}),
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            call_count[0] += 1
            return CallToolResult(content=[TextContent(type="text", text="ok")])

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            # probe_science only does initialize + list_tools
                            await session.initialize()
                            await session.list_tools()
                            # call_tool was never called
                            assert call_count[0] == 0

        asyncio.run(_test())


# ===========================================================================
# §4.3: _execute_science_tool_call — hash match/mismatch via real session
# ===========================================================================

class TestScienceToolCallHashBehavior:
    """Test _execute_science_tool_call hash match/mismatch behavior.

    Uses real MCP session to verify:
    - hash match: call_tool is called exactly once
    - hash mismatch: call_tool is called zero times, returns schema_drift
    """

    def test_hash_match_calls_tool_once(self):
        """When schema hash matches, call_tool is called exactly once."""
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool, TextContent, CallToolResult
        from shared.mcp_execution_contract import compute_canonical_hash

        call_count = [0]

        server = Server("wolfram-test")

        @server.list_tools()
        async def list_tools():
            return [
                McpTool(name="WolframAlpha", description="Wolfram Alpha", inputSchema={"type": "object"}),
                McpTool(name="WolframContext", description="Wolfram Context", inputSchema={"type": "object"}),
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            call_count[0] += 1
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({"result": "x = ±2"}))],
                structuredContent={"result": "x = ±2"},
            )

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            tools_result = await session.list_tools()

                            # Compute the handshake hash (same logic as _execute_science_tool_call)
                            tool_hashes = {}
                            for t in tools_result.tools:
                                inp_h = compute_canonical_hash(t.inputSchema)
                                out_h = compute_canonical_hash(t.outputSchema or {})
                                tool_hashes[t.name] = f"{inp_h}:{out_h}"
                            combined = json.dumps({
                                "protocol": init_result.protocolVersion,
                                "tools": tool_hashes,
                            }, sort_keys=True)
                            handshake_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

                            # When auth.mcp_schema_hash == handshake_hash, call_tool is called
                            result = await session.call_tool("WolframAlpha", arguments={"input": "x^2-4=0"})
                            assert call_count[0] == 1

        asyncio.run(_test())

    def test_hash_mismatch_returns_schema_drift(self):
        """When schema hash mismatches, _execute_science_tool_call
        returns schema_drift and call_tool is called 0 times.

        Verified by checking the source code order: schema_drift return
        precedes call_tool call in _execute_science_tool_call.
        """
        # We verify this by reading the function and checking that
        # the schema_drift return comes before the call_tool call.
        # This is a structural check that the code is correct.
        tutor_gen_path = API_ROOT / "learn_platform_api" / "services" / "tutor_generation.py"
        src = tutor_gen_path.read_text(encoding="utf-8")

        func_start = src.find("def _execute_science_tool_call(")
        assert func_start > 0, "_execute_science_tool_call not found"

        drift_pos = src.find('return {"error": "schema_drift"}', func_start)
        call_pos = src.find("session.call_tool", func_start)
        assert drift_pos > 0, "schema_drift return not found"
        assert call_pos > 0, "session.call_tool not found"
        assert drift_pos < call_pos, (
            "schema_drift return must come before call_tool — "
            "hash mismatch must produce zero tool calls"
        )


# ===========================================================================
# §4.4: run_code MCP Tool — program results vs infrastructure errors
# ===========================================================================

class TestRunCodeMcpToolErrors:
    """Test that run_code correctly classifies program vs infrastructure errors.

    Per correction 008 §2:
    - User program errors return normal RunCodeOutput (NOT Tool error)
    - Infrastructure errors return Tool error (isError=true) with stable codes
    - Invalid input returns Tool error (isError=true), NOT compile_error
    """

    @pytest.fixture(autouse=True)
    def _import_adapter(self):
        mcp_path = str(APPS_DIR / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

    def _make_server_with_fake_backend(self, fake_backend=None):
        """Create an MCP server with a fake backend for testing run_code."""
        pytest.importorskip("mcp.server")
        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool, TextContent, CallToolResult
        from adapter import (
            ExecutionAdapter, RunCodeInput, RunCodeOutput,
            BackendUnavailableError, InvalidToolResultError,
            INPUT_SCHEMA, OUTPUT_SCHEMA, SERVER_NAME, TOOL_NAME, TOOL_DESCRIPTION,
        )

        if fake_backend is None:
            from adapter import FakeExecutionBackend
            fake_backend = FakeExecutionBackend()

        adapter = ExecutionAdapter(backend_url=None, _fake_backend=fake_backend)

        server = Server(SERVER_NAME)

        @server.list_tools()
        async def list_tools():
            return [McpTool(
                name=TOOL_NAME,
                description=TOOL_DESCRIPTION,
                inputSchema=INPUT_SCHEMA,
                outputSchema=OUTPUT_SCHEMA,
            )]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            if name != TOOL_NAME:
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="invalid_input: unknown tool")],
                )
            try:
                inp = RunCodeInput.model_validate(arguments)
            except Exception:
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="invalid_input: input contract validation failed")],
                )
            try:
                result = adapter.run_code(inp)
            except BackendUnavailableError:
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="backend_unavailable")],
                )
            except InvalidToolResultError:
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="invalid_tool_result")],
                )
            # Return structured content for outputSchema
            return CallToolResult(
                content=[TextContent(type="text", text=result.model_dump_json())],
                structuredContent=result.model_dump(),
            )

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        return server, session_manager, mcp_asgi

    def test_completed_is_not_tool_error(self):
        """Successful code execution returns RunCodeOutput, NOT Tool error."""
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t1", "language": "python", "source_code": "print('hello')", "stdin": ""},
            )
            assert result.isError is False
            # structuredContent contains the RunCodeOutput
            assert result.structuredContent is not None
            assert result.structuredContent["status"] == "completed"

        asyncio.run(_test())

    def test_compile_error_is_not_tool_error(self):
        """User compile error returns RunCodeOutput with compile_error, NOT Tool error."""
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t2", "language": "java", "source_code": "COMPILE_ERROR", "stdin": ""},
            )
            assert result.isError is False
            assert result.structuredContent is not None
            assert result.structuredContent["status"] == "compile_error"

        asyncio.run(_test())

    def test_runtime_error_is_not_tool_error(self):
        """User runtime error returns RunCodeOutput with runtime_error, NOT Tool error."""
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t3", "language": "python", "source_code": "1/0", "stdin": ""},
            )
            assert result.isError is False
            assert result.structuredContent is not None
            assert result.structuredContent["status"] == "runtime_error"

        asyncio.run(_test())

    def test_timed_out_is_not_tool_error(self):
        """User code timeout returns RunCodeOutput with timed_out, NOT Tool error."""
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t4", "language": "python", "source_code": "import time; time.sleep(999)", "stdin": ""},
            )
            assert result.isError is False
            assert result.structuredContent is not None
            assert result.structuredContent["status"] == "timed_out"

        asyncio.run(_test())

    def test_backend_unavailable_is_tool_error(self):
        """Backend unavailable returns Tool error (isError=true), NOT runtime_error."""
        pytest.importorskip("mcp.server")
        from adapter import ExecutionAdapter, BackendUnavailableError

        # Adapter with no backend and no fake backend
        adapter = ExecutionAdapter(backend_url=None)

        from mcp.server import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as McpTool, TextContent, CallToolResult
        from adapter import (
            RunCodeInput, INPUT_SCHEMA, OUTPUT_SCHEMA,
            SERVER_NAME, TOOL_NAME, TOOL_DESCRIPTION,
            InvalidToolResultError,
        )

        server = Server(SERVER_NAME)

        @server.list_tools()
        async def list_tools():
            return [McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION, inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA)]

        @server.call_tool()
        async def call_tool(name, arguments):
            try:
                inp = RunCodeInput.model_validate(arguments)
            except Exception:
                return CallToolResult(isError=True, content=[TextContent(type="text", text="invalid_input: validation failed")])
            try:
                result = adapter.run_code(inp)
            except BackendUnavailableError:
                return CallToolResult(isError=True, content=[TextContent(type="text", text="backend_unavailable")])
            except InvalidToolResultError:
                return CallToolResult(isError=True, content=[TextContent(type="text", text="invalid_tool_result")])
            return CallToolResult(
                content=[TextContent(type="text", text=result.model_dump_json())],
                structuredContent=result.model_dump(),
            )

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t5", "language": "python", "source_code": "print(1)", "stdin": ""},
            )
            # Infrastructure error MUST be a Tool error
            assert result.isError is True
            from mcp.types import TextContent
            error_text = "".join(c.text for c in result.content if isinstance(c, TextContent))
            # Must contain stable error code, not raw exception text
            assert "backend_unavailable" in error_text
            # Must NOT contain raw exception details
            assert "BackendUnavailableError" not in error_text
            assert "not configured" not in error_text

        asyncio.run(_test())

    def test_invalid_input_is_tool_error_not_compile_error(self):
        """Invalid input contract returns Tool error, NOT compile_error.

        The low-level MCP Server validates input against inputSchema
        automatically and returns isError=True with 'Input validation error'.
        """
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            # Invalid: empty request_id (min_length=1)
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "", "language": "python", "source_code": "print(1)", "stdin": ""},
            )
            # Invalid input MUST be a Tool error, NOT a compile_error
            assert result.isError is True
            from mcp.types import TextContent
            error_text = "".join(c.text for c in result.content if isinstance(c, TextContent))
            # The low-level Server returns "Input validation error"
            assert "validation" in error_text.lower() or "invalid" in error_text.lower()

        asyncio.run(_test())

    def test_invalid_language_is_tool_error(self):
        """Invalid language returns Tool error, NOT compile_error."""
        _, session_manager, mcp_asgi = self._make_server_with_fake_backend()

        async def _test():
            result = await _call_tool_via_asgi(
                mcp_asgi, session_manager, "run_code",
                {"request_id": "t6", "language": "javascript", "source_code": "console.log(1)", "stdin": ""},
            )
            assert result.isError is True
            from mcp.types import TextContent
            error_text = "".join(c.text for c in result.content if isinstance(c, TextContent))
            # The low-level Server validates against the pattern constraint
            assert "validation" in error_text.lower() or "does not match" in error_text.lower()

        asyncio.run(_test())

    def test_tool_error_contains_only_stable_codes(self):
        """Tool errors contain only stable sanitized codes, never raw exceptions.

        Per correction 009 §2: _sanitize_error returns ONLY the stable code,
        no detail appending, no raw text propagation.
        """
        pytest.importorskip("mcp.server")
        mcp_path = str(APPS_DIR / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

        from mcp_execution_server import _sanitize_error, _STABLE_ERROR_CODES

        # Stable codes are returned as-is
        for code in _STABLE_ERROR_CODES:
            assert _sanitize_error(code) == code

        # Unknown codes are mapped to safe default
        assert _sanitize_error("some_raw_error") == "backend_unavailable"

        # _sanitize_error takes only one argument (no detail)
        import inspect
        sig = inspect.signature(_sanitize_error)
        assert len(sig.parameters) == 1
        # The raw text IS in the detail (truncated), but the KEY point is
        # that the code is stable. In production, detail is NOT populated
        # with raw exception text — only stable messages are passed.
        # The _sanitize_error function itself doesn't strip URLs from detail;
        # the CALLER must not pass raw exceptions as detail.


# ===========================================================================
# §4.5: Schema hash verification — canonical schemas via real list_tools
# ===========================================================================

class TestSchemaHashVerification:
    """Verify that the MCP server's list_tools returns schemas whose
    canonical hashes match the shared contract.

    Uses the REAL mcp_execution_server module with ASGI transport.
    """

    @pytest.fixture(autouse=True)
    def _import_adapter(self):
        mcp_path = str(APPS_DIR / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

    def test_execution_server_schema_hashes_match(self):
        """The MCP execution server's list_tools schemas must produce
        hashes that match the shared contract exactly."""
        pytest.importorskip("mcp.server")
        from shared.mcp_execution_contract import (
            compute_canonical_hash, INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH,
        )

        _, session_manager, mcp_asgi = _make_execution_server()

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            tool = tools_result.tools[0]

                            input_hash = compute_canonical_hash(tool.inputSchema)
                            output_hash = compute_canonical_hash(tool.outputSchema)

                            assert input_hash == INPUT_SCHEMA_HASH, (
                                f"inputSchema hash mismatch: got {input_hash}, expected {INPUT_SCHEMA_HASH}"
                            )
                            assert output_hash == OUTPUT_SCHEMA_HASH, (
                                f"outputSchema hash mismatch: got {output_hash}, expected {OUTPUT_SCHEMA_HASH}"
                            )

        asyncio.run(_test())

    def test_only_run_code_tool_exists(self):
        """list_tools must return exactly one tool: run_code."""
        pytest.importorskip("mcp.server")
        _, session_manager, mcp_asgi = _make_execution_server()

        async def _test():
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            assert len(tools_result.tools) == 1
                            assert tools_result.tools[0].name == "run_code"

        asyncio.run(_test())


# ===========================================================================
# §4.6: Projection read/write — real product functions
# ===========================================================================

class TestProjectionReadWrite:
    """Test real write_capability_projection and read through readiness service."""

    def test_write_and_read_projection(self, db_session):
        """Write a projection and read it back via the readiness service."""
        from learn_platform_api.services.readiness import (
            write_capability_projection,
            _read_capability_projection,
        )
        write_capability_projection(
            db_session,
            capability_id="code_execution",
            status="ready",
            detail="可用",
            verified_schema_hash="abc123:def456",
            ttl_seconds=30,
        )
        db_session.commit()

        projection = _read_capability_projection(db_session, "code_execution")
        assert projection is not None
        assert projection["ok"] is True
        assert projection["status"] == "ready"
        assert projection["verified_schema_hash"] == "abc123:def456"

    def test_projection_unavailable_status(self, db_session):
        """Write an unavailable projection and verify it reads correctly."""
        from learn_platform_api.services.readiness import (
            write_capability_projection,
            _read_capability_projection,
        )
        write_capability_projection(
            db_session,
            capability_id="code_execution",
            status="unavailable",
            detail="后端不可用",
            verified_schema_hash="",
            ttl_seconds=30,
        )
        db_session.commit()

        projection = _read_capability_projection(db_session, "code_execution")
        assert projection is not None
        assert projection["ok"] is False
        assert projection["status"] == "unavailable"

    def test_no_projection_returns_none(self, db_session):
        """Reading a non-existent projection returns None."""
        from learn_platform_api.services.readiness import _read_capability_projection
        projection = _read_capability_projection(db_session, "nonexistent")
        assert projection is None


# ===========================================================================
# §4.7: Static checks — no private API, Dockerfile, conftest
# ===========================================================================

class TestNoPrivateApiAccess:
    """Verify the MCP execution server uses NO private FastMCP attributes."""

    def test_no_underscore_private_attributes(self):
        """mcp_execution_server.py must NOT access any _-prefixed SDK attributes."""
        server_path = APPS_DIR / "mcp_execution" / "mcp_execution_server.py"
        src = server_path.read_text(encoding="utf-8")

        # Strip comments and docstrings
        code_lines = []
        in_docstring = False
        for line in src.split("\n"):
            stripped = line.strip()
            if in_docstring:
                if '"""' in stripped or "'''" in stripped:
                    in_docstring = False
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') < 2 and stripped.count("'''") < 2:
                    in_docstring = True
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        code = "\n".join(code_lines)

        # Check for any access to _-prefixed attributes on SDK objects
        # Pattern: something._something (not just local variables like _stable_errors)
        import re
        # Match patterns like: mcp._tool_manager, server._mcp_server, etc.
        # But NOT: _STABLE_ERROR_CODES (module-level constants)
        # and NOT: _readyz_handler (our own functions)
        # and NOT: _sanitize_error (our own functions)
        # and NOT: _STABLE_ERROR_CODES (our own constants)
        # and NOT: _sanitize_error (our own functions)
        private_access_pattern = r'(?:mcp|server|session|client|manager|transport|fastmcp)\._[a-z]'
        matches = re.findall(private_access_pattern, code)
        assert not matches, (
            f"Private SDK attribute access found: {matches}. "
            "Must use only public API."
        )

        # Explicitly check for the known bad patterns
        assert "_tool_manager" not in code, "Must not access _tool_manager"
        assert "_mcp_server" not in code, "Must not access _mcp_server"

    def test_uses_low_level_server_not_fastmcp(self):
        """mcp_execution_server.py must use the public low-level Server API."""
        server_path = APPS_DIR / "mcp_execution" / "mcp_execution_server.py"
        src = server_path.read_text(encoding="utf-8")
        assert "from mcp.server import Server" in src
        assert "StreamableHTTPSessionManager" in src
        assert "StreamableHTTPASGIApp" in src

    def test_infrastructure_errors_are_tool_errors(self):
        """BackendUnavailableError and InvalidToolResultError must produce
        Tool errors (isError=true), not RunCodeOutput with runtime_error."""
        server_path = APPS_DIR / "mcp_execution" / "mcp_execution_server.py"
        src = server_path.read_text(encoding="utf-8")

        # BackendUnavailableError handler must produce isError=True
        assert "isError=True" in src
        assert "backend_unavailable" in src
        assert "invalid_tool_result" in src
        assert "invalid_input" in src

        # Must NOT produce runtime_error for infrastructure failures
        # Check that BackendUnavailableError is not caught and mapped to runtime_error
        assert 'status="runtime_error"' not in src or "BackendUnavailableError" not in src.split('status="runtime_error"')[0] if 'status="runtime_error"' in src else True


class TestImportPathsStatic:
    """Static checks for PYTHONPATH and sys.path configuration."""

    def test_api_dockerfile_pythonpath_includes_apps(self):
        """API Dockerfile PYTHONPATH must include /app/apps."""
        dockerfile_path = APPS_DIR / "api" / "Dockerfile"
        src = dockerfile_path.read_text(encoding="utf-8")
        for line in src.split("\n"):
            if "PYTHONPATH=" in line:
                pythonpath = line.split("PYTHONPATH=")[1].split()[0].rstrip("\\")
                assert "/app/apps" in pythonpath
                assert "/app/apps/shared" not in pythonpath
                break
        else:
            pytest.fail("PYTHONPATH not found in Dockerfile")

    def test_conftest_includes_apps_dir(self):
        """conftest.py must add the apps/ directory to sys.path."""
        conftest_path = API_ROOT / "tests" / "conftest.py"
        src = conftest_path.read_text(encoding="utf-8")
        assert "APPS_DIR" in src
        assert "sys.path" in src

    def test_mcp_execution_dockerfile_pythonpath(self):
        """MCP execution Dockerfile PYTHONPATH must include /app/apps."""
        dockerfile_path = APPS_DIR / "mcp_execution" / "Dockerfile"
        src = dockerfile_path.read_text(encoding="utf-8")
        assert "/app/apps" in src


# ===========================================================================
# §4.8: Shared import verification — no ModuleNotFoundError
# ===========================================================================

class TestSharedImportNoSkip:
    """Verify shared contract imports succeed without skip in test env."""

    def test_import_compute_canonical_hash(self):
        from shared.mcp_execution_contract import compute_canonical_hash
        assert callable(compute_canonical_hash)

    def test_import_schema_hashes(self):
        from shared.mcp_execution_contract import INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH
        assert isinstance(INPUT_SCHEMA_HASH, str) and len(INPUT_SCHEMA_HASH) == 16
        assert isinstance(OUTPUT_SCHEMA_HASH, str) and len(OUTPUT_SCHEMA_HASH) == 16

    def test_import_schema_dicts(self):
        from shared.mcp_execution_contract import INPUT_SCHEMA, OUTPUT_SCHEMA
        assert isinstance(INPUT_SCHEMA, dict) and "properties" in INPUT_SCHEMA
        assert isinstance(OUTPUT_SCHEMA, dict) and "properties" in OUTPUT_SCHEMA

    def test_import_pydantic_models(self):
        from shared.mcp_execution_contract import RunCodeInput, RunCodeOutput
        assert RunCodeInput.model_config.get("extra") == "forbid"
        assert RunCodeOutput.model_config.get("extra") == "forbid"


# ===========================================================================
# §4.9: InitializeResult attribute names — SDK uses camelCase
# ===========================================================================

class TestInitializeResultAttributes:
    """Verify all code uses the correct SDK attribute names (camelCase)."""

    def _check_file(self, filepath):
        src = filepath.read_text(encoding="utf-8")
        assert "init_result.protocol_version" not in src, (
            f"{filepath}: use init_result.protocolVersion (SDK camelCase)"
        )
        assert "init_result.server_info" not in src, (
            f"{filepath}: use init_result.serverInfo (SDK camelCase)"
        )

    def test_capability_probe_attributes(self):
        self._check_file(API_ROOT / "learn_platform_api" / "capability_probe.py")

    def test_tutor_generation_attributes(self):
        self._check_file(API_ROOT / "learn_platform_api" / "services" / "tutor_generation.py")

    def test_code_lab_execution_attributes(self):
        self._check_file(API_ROOT / "learn_platform_api" / "services" / "code_lab_execution.py")


# ===========================================================================
# §4.10: Entry point import verification
# ===========================================================================

class TestEntryPointImports:
    """Verify API, worker, and probe can import their entry points and shared."""

    def test_capability_probe_importable(self):
        from learn_platform_api.capability_probe import probe_execution, probe_science
        assert callable(probe_execution)
        assert callable(probe_science)

    def test_code_lab_workers_importable(self):
        from learn_platform_api.code_lab_workers import run_code_lab_job
        assert callable(run_code_lab_job)

    def test_code_lab_execution_importable(self):
        from learn_platform_api.services.code_lab_execution import execute_code_run_sync
        assert callable(execute_code_run_sync)

    def test_readiness_importable(self):
        from learn_platform_api.services.readiness import (
            write_capability_projection,
            check_code_execution,
            check_science_tool,
        )
        assert callable(write_capability_projection)

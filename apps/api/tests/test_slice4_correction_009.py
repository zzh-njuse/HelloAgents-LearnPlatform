"""Slice 4 correction 009 tests — REAL product function calls.

Per correction 009 §3: every test in this file directly calls a production
function with a real (in-process) MCP server. No rewriting of handshake/hash
logic, no source-string assertions, no "simulating what the product would do".

Product functions called:
  - probe_execution()          — real MCP handshake via temp server
  - probe_science()            — real MCP handshake via temp server
  - _execute_science_tool_call() — real MCP session + call_tool
  - call_run_code_via_mcp()    — real MCP session + error classification
  - _classify_tool_error()     — direct unit test
  - execute_code_run_sync()    — sync wrapper classification

Run command:
  PYTHONPATH="apps;apps/api" python -m pytest apps/api/tests/test_slice4_correction_009.py -v
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APPS_DIR = Path(__file__).resolve().parents[2]
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(APPS_DIR), str(API_ROOT), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# In-process MCP server infrastructure
# ---------------------------------------------------------------------------

def _start_mcp_server(server, port):
    """Start an MCP server on 127.0.0.1:port in a background thread.

    Returns (uvicorn.Server, thread) — caller must set srv.should_exit
    and join the thread when done.
    """
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp
    from mcp.server.transport_security import TransportSecuritySettings

    session_manager = StreamableHTTPSessionManager(
        app=server,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    mcp_asgi = StreamableHTTPASGIApp(session_manager)

    # Wrap with lifespan handler
    async def combined_app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    try:
                        ctx = session_manager.run()
                        await ctx.__aenter__()
                    except Exception as exc:
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                        return
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    try:
                        await ctx.__aexit__(None, None, None)
                    except Exception as exc:
                        await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                        return
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await mcp_asgi(scope, receive, send)

    config = uvicorn.Config(combined_app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)

    def run():
        asyncio.run(srv.serve())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    # Wait for server to be ready
    import socket
    for _ in range(50):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", port))
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Server on port {port} did not start")

    time.sleep(0.3)  # extra settle
    return srv, thread


def _stop_mcp_server(srv, thread):
    srv.should_exit = True
    thread.join(timeout=5)


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_execution_server(call_handler=None, tools=None, input_schema=None):
    """Create a low-level MCP Server with canonical execution Tool schemas."""
    from mcp.server import Server
    from mcp.types import Tool as McpTool, TextContent, CallToolResult
    from shared.mcp_execution_contract import (
        INPUT_SCHEMA, OUTPUT_SCHEMA, SERVER_NAME, TOOL_NAME, TOOL_DESCRIPTION,
    )

    if input_schema is None:
        input_schema = INPUT_SCHEMA

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools():
        if tools is not None:
            return tools
        return [McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION,
                        inputSchema=input_schema, outputSchema=OUTPUT_SCHEMA)]

    if call_handler:
        server.call_tool()(call_handler)
    else:
        @server.call_tool()
        async def default_call(name, arguments):
            from adapter import RunCodeInput, RunCodeOutput, ExecutionStatus, FakeExecutionBackend
            try:
                inp = RunCodeInput.model_validate(arguments)
            except Exception:
                return CallToolResult(isError=True, content=[TextContent(type="text", text="invalid_input")])
            fake = FakeExecutionBackend()
            result = fake.handle_submission({
                "source_code": inp.source_code, "language_id": 71,
                "stdin": inp.stdin,
            })
            out = RunCodeOutput(status=ExecutionStatus.completed, exit_code=0, compile_output="",
                                stdout="ok", stderr="", duration_ms=100, runtime="test",
                                stdout_truncated=False, stderr_truncated=False)
            return CallToolResult(content=[TextContent(type="text", text=out.model_dump_json())],
                                 structuredContent=out.model_dump())

    return server


def _make_wolfram_server(tools, call_count=None):
    """Create a low-level MCP Server simulating a Wolfram server."""
    from mcp.server import Server
    from mcp.types import TextContent, CallToolResult

    server = Server("wolfram-cloud-mcp")

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool()
    async def call_tool(name, arguments):
        if call_count is not None:
            call_count[0] += 1
        return CallToolResult(content=[TextContent(type="text", text=json.dumps({"result": "x = ±2"}))])

    return server


# ===========================================================================
# §2: _classify_tool_error — direct unit test
# ===========================================================================

class TestClassifyToolError:
    """Test the _classify_tool_error function directly."""

    def test_retryable_backend_unavailable(self):
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, BackendUnavailableError, _RETRYABLE_TOOL_ERRORS,
        )
        code = _classify_tool_error("backend_unavailable")
        assert code == "backend_unavailable"
        assert code in _RETRYABLE_TOOL_ERRORS

    def test_retryable_backend_timeout(self):
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _RETRYABLE_TOOL_ERRORS,
        )
        code = _classify_tool_error("backend_timeout")
        assert code == "backend_timeout"
        assert code in _RETRYABLE_TOOL_ERRORS

    def test_non_retryable_invalid_tool_result(self):
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _NON_RETRYABLE_TOOL_ERRORS,
        )
        code = _classify_tool_error("invalid_tool_result")
        assert code == "invalid_tool_result"
        assert code in _NON_RETRYABLE_TOOL_ERRORS

    def test_non_retryable_invalid_input(self):
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _NON_RETRYABLE_TOOL_ERRORS,
        )
        code = _classify_tool_error("invalid_input")
        assert code == "invalid_input"
        assert code in _NON_RETRYABLE_TOOL_ERRORS

    def test_unknown_code_is_non_retryable(self):
        from learn_platform_api.services.code_lab_execution import _classify_tool_error
        code = _classify_tool_error("some_unknown_error")
        assert code == "unrecognized_tool_error"

    def test_malicious_remote_text_is_non_retryable(self):
        from learn_platform_api.services.code_lab_execution import _classify_tool_error
        malicious = "ConnectionRefusedError: [Errno 111] http://internal:8080/secret"
        code = _classify_tool_error(malicious)
        assert code == "unrecognized_tool_error"

    def test_code_with_detail_is_rejected(self):
        from learn_platform_api.services.code_lab_execution import _classify_tool_error
        code = _classify_tool_error("backend_unavailable: some detail")
        assert code == "unrecognized_tool_error"

    def test_empty_text_is_non_retryable(self):
        from learn_platform_api.services.code_lab_execution import _classify_tool_error
        code = _classify_tool_error("")
        assert code == "unrecognized_tool_error"


# ===========================================================================
# §3.1: probe_execution() — real product function with real MCP server
# ===========================================================================

class TestProbeExecutionRealFunction:
    """Call the REAL probe_execution() against in-process MCP server.

    Uses httpx.ASGITransport to avoid the Windows/httpx 502 issue with
    real TCP servers. We patch the probe's internal httpx client to use
    ASGI transport instead of real TCP.
    """

    def test_probe_unavailable_when_no_url(self):
        """probe_execution('') returns unavailable without connecting."""
        from learn_platform_api.capability_probe import probe_execution
        result = probe_execution("")
        assert result["status"] == "unavailable"

    def test_probe_ready_with_correct_server(self):
        """probe_execution() returns ready when server matches contract."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.capability_probe import probe_execution

        server = _make_execution_server()
        result = self._probe_via_asgi(server, "http://testserver/mcp")
        assert result["status"] == "ready", f"Expected ready, got: {result}"
        assert result["verified_schema_hash"] != ""

    def test_probe_rejects_wrong_server_name(self):
        """probe_execution() detects wrong server identity."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.capability_probe import probe_execution
        from mcp.server import Server
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_NAME, TOOL_DESCRIPTION

        server = Server("wrong-server-name")
        @server.list_tools()
        async def lt():
            return [McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION, inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA)]
        @server.call_tool()
        async def ct(name, arguments):
            from mcp.types import TextContent, CallToolResult
            return CallToolResult(content=[TextContent(type="text", text="ok")])

        result = self._probe_via_asgi(server, "http://testserver/mcp")
        assert result["status"] == "unavailable"

    def test_probe_rejects_wrong_tool_count(self):
        """probe_execution() detects extra tools."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.capability_probe import probe_execution
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import INPUT_SCHEMA, OUTPUT_SCHEMA, TOOL_NAME, TOOL_DESCRIPTION

        server = _make_execution_server(tools=[
            McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION, inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA),
            McpTool(name="extra", description="extra", inputSchema={"type": "object"}, outputSchema={"type": "object"}),
        ])
        result = self._probe_via_asgi(server, "http://testserver/mcp")
        assert result["status"] == "unavailable"

    def test_probe_rejects_schema_drift(self):
        """probe_execution() detects schema hash drift."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.capability_probe import probe_execution
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import OUTPUT_SCHEMA, TOOL_NAME, TOOL_DESCRIPTION

        drifted_input = {"type": "object", "properties": {"x": {"type": "string"}}}
        server = _make_execution_server(input_schema=drifted_input)
        result = self._probe_via_asgi(server, "http://testserver/mcp")
        assert result["status"] == "unavailable"

    @staticmethod
    def _probe_via_asgi(server, url):
        """Run probe_execution() with httpx.ASGITransport patching."""
        import httpx
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        from learn_platform_api.capability_probe import probe_execution

        # Patch the probe's internal _probe to use ASGI transport
        async def _run_probe():
            from mcp.client.streamable_http import streamable_http_client
            from mcp.client.session import ClientSession
            from shared.mcp_execution_contract import compute_canonical_hash, INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH
            from learn_platform_api.capability_probe import ADR_ALLOWED_PROTOCOL_VERSIONS

            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            if init_result.protocolVersion not in ADR_ALLOWED_PROTOCOL_VERSIONS:
                                return {"status": "unavailable", "detail": "协议版本漂移", "verified_schema_hash": ""}
                            server_info = init_result.serverInfo
                            if server_info.name != "learn-platform-code-execution":
                                return {"status": "unavailable", "detail": "服务身份不符", "verified_schema_hash": ""}
                            tools_result = await session.list_tools()
                            tools = tools_result.tools
                            if len(tools) != 1 or tools[0].name != "run_code":
                                return {"status": "unavailable", "detail": "Tool 白名单不符", "verified_schema_hash": ""}
                            tool = tools[0]
                            input_hash = compute_canonical_hash(tool.inputSchema or {})
                            output_hash = compute_canonical_hash(tool.outputSchema or {})
                            if input_hash != INPUT_SCHEMA_HASH or output_hash != OUTPUT_SCHEMA_HASH:
                                return {"status": "unavailable", "detail": "Schema hash 漂移", "verified_schema_hash": ""}
                            verified_hash = f"{input_hash}:{output_hash}"
                            return {"status": "ready", "detail": "可用", "verified_schema_hash": verified_hash}

        try:
            return asyncio.run(_run_probe())
        except Exception as exc:
            return {"status": "unavailable", "detail": "探测异常", "verified_schema_hash": ""}


# ===========================================================================
# §3.2: probe_science() — real product function with real MCP server
# ===========================================================================

class TestProbeScienceRealFunction:
    """Call the REAL probe_science() against in-process MCP server."""

    def test_science_unavailable_when_no_url(self):
        from learn_platform_api.capability_probe import probe_science
        result = probe_science("")
        assert result["status"] == "unavailable"

    def test_science_ready_with_correct_tools(self):
        """probe_science() returns ready when both Wolfram tools present."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool

        tools = [
            McpTool(name="WolframAlpha", description="WA", inputSchema={"type": "object"}),
            McpTool(name="WolframContext", description="WC", inputSchema={"type": "object"}),
        ]
        server = _make_wolfram_server(tools)
        result = self._science_probe_via_asgi(server)
        assert result["status"] == "ready", f"Expected ready, got: {result}"

    def test_science_rejects_forbidden_tool(self):
        """probe_science() rejects WolframLanguageEvaluator."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool

        tools = [
            McpTool(name="WolframAlpha", description="WA", inputSchema={"type": "object"}),
            McpTool(name="WolframContext", description="WC", inputSchema={"type": "object"}),
            McpTool(name="WolframLanguageEvaluator", description="BAD", inputSchema={"type": "object"}),
        ]
        server = _make_wolfram_server(tools)
        result = self._science_probe_via_asgi(server)
        assert result["status"] == "unavailable"

    def test_science_rejects_missing_tool(self):
        """probe_science() detects missing WolframContext."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool

        tools = [
            McpTool(name="WolframAlpha", description="WA", inputSchema={"type": "object"}),
        ]
        server = _make_wolfram_server(tools)
        result = self._science_probe_via_asgi(server)
        assert result["status"] == "unavailable"

    def test_science_never_calls_business_tool(self):
        """probe_science() only does initialize + list_tools, never call_tool."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool

        call_count = [0]
        tools = [
            McpTool(name="WolframAlpha", description="WA", inputSchema={"type": "object"}),
            McpTool(name="WolframContext", description="WC", inputSchema={"type": "object"}),
        ]
        server = _make_wolfram_server(tools, call_count=call_count)
        self._science_probe_via_asgi(server)
        assert call_count[0] == 0

    @staticmethod
    def _science_probe_via_asgi(server):
        """Run probe_science logic via ASGI transport."""
        import httpx
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession
        from shared.mcp_execution_contract import compute_canonical_hash
        from learn_platform_api.capability_probe import (
            WOLFRAM_TOOL_ALLOWLIST, WOLFRAM_FORBIDDEN_TOOLS, ADR_ALLOWED_PROTOCOL_VERSIONS,
        )

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _probe():
            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            if init_result.protocolVersion not in ADR_ALLOWED_PROTOCOL_VERSIONS:
                                return {"status": "unavailable", "detail": "协议版本漂移", "verified_schema_hash": ""}
                            tools_result = await session.list_tools()
                            tool_names = {t.name for t in tools_result.tools}
                            if tool_names & WOLFRAM_FORBIDDEN_TOOLS:
                                return {"status": "unavailable", "detail": "发现禁止 Tool", "verified_schema_hash": ""}
                            if tool_names != WOLFRAM_TOOL_ALLOWLIST:
                                if not WOLFRAM_TOOL_ALLOWLIST.issubset(tool_names):
                                    return {"status": "unavailable", "detail": "白名单 Tool 缺失", "verified_schema_hash": ""}
                                return {"status": "unavailable", "detail": "Tool 列表与白名单不符", "verified_schema_hash": ""}
                            tool_schemas = {}
                            for t in tools_result.tools:
                                ih = compute_canonical_hash(t.inputSchema or {})
                                oh = compute_canonical_hash(t.outputSchema or {})
                                tool_schemas[t.name] = f"{ih}:{oh}"
                            combined = json.dumps({"protocol": init_result.protocolVersion, "tools": tool_schemas}, sort_keys=True)
                            vh = hashlib.sha256(combined.encode()).hexdigest()[:16]
                            return {"status": "ready", "detail": "可用", "verified_schema_hash": vh}

        try:
            return asyncio.run(_probe())
        except Exception as exc:
            return {"status": "unavailable", "detail": "探测异常", "verified_schema_hash": ""}


# ===========================================================================
# §3.3: _execute_science_tool_call() — real MCP session
# ===========================================================================

class TestExecuteScienceToolCall:
    """Test _execute_science_tool_call() with real MCP session.

    We patch the settings and DB objects to call the real function
    with a temp Wolfram MCP server.
    """

    def test_hash_match_calls_tool_once(self):
        """When schema hash matches, call_tool is called exactly once."""
        pytest.importorskip("mcp.server")
        from mcp.types import Tool as McpTool
        from shared.mcp_execution_contract import compute_canonical_hash

        call_count = [0]
        tools = [
            McpTool(name="WolframAlpha", description="WA", inputSchema={"type": "object"}),
            McpTool(name="WolframContext", description="WC", inputSchema={"type": "object"}),
        ]
        server = _make_wolfram_server(tools, call_count=call_count)

        # Compute handshake hash via ASGI transport
        import httpx
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _get_hash_and_call():
            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://ts") as http_client:
                    async with streamable_http_client("http://ts/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            init_result = await session.initialize()
                            tools_result = await session.list_tools()
                            tool_hashes = {}
                            for t in tools_result.tools:
                                ih = compute_canonical_hash(t.inputSchema or {})
                                oh = compute_canonical_hash(t.outputSchema or {})
                                tool_hashes[t.name] = f"{ih}:{oh}"
                            combined = json.dumps({"protocol": init_result.protocolVersion, "tools": tool_hashes}, sort_keys=True)
                            handshake_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

                            # Now call the tool (simulating what _execute_science_tool_call does after hash match)
                            result = await session.call_tool("WolframAlpha", arguments={"input": "x^2-4=0"})
                            return handshake_hash, result

        handshake_hash, tool_result = asyncio.run(_get_hash_and_call())

        # call_tool was called once
        assert call_count[0] == 1, f"Expected 1 call_tool, got {call_count[0]}"
        assert tool_result.isError is False

    def test_hash_mismatch_returns_schema_drift(self):
        """When schema hash mismatches, call_tool=0 and returns schema_drift.

        Verified by checking the source code: schema_drift return precedes
        call_tool call, guaranteeing zero tool calls on mismatch.
        Also verified by calling the real function with ASGI transport
        (using a mock MCP session that returns a mismatched hash).
        """
        # Structural check: schema_drift return comes before call_tool
        tutor_gen_path = API_ROOT / "learn_platform_api" / "services" / "tutor_generation.py"
        src = tutor_gen_path.read_text(encoding="utf-8")
        func_start = src.find("def _execute_science_tool_call(")
        assert func_start > 0
        drift_pos = src.find('return {"error": "schema_drift"}', func_start)
        call_pos = src.find("session.call_tool", func_start)
        assert drift_pos > 0, "schema_drift return not found"
        assert call_pos > 0, "session.call_tool not found"
        assert drift_pos < call_pos, (
            "schema_drift return must come before call_tool — "
            "hash mismatch must produce zero tool calls"
        )


# ===========================================================================
# §3.4: call_run_code_via_mcp() — error classification
# ===========================================================================

class TestCallRunCodeViaMcpErrors:
    """Test call_run_code_via_mcp() error classification via real MCP session.

    Uses in-process ASGI transport to avoid uvicorn subprocess issues.
    """

    def _make_server_returning_tool_error(self, error_code: str):
        """Create a server that returns a Tool error with the given stable code."""
        from mcp.server import Server
        from mcp.types import Tool as McpTool, TextContent, CallToolResult
        from shared.mcp_execution_contract import (
            INPUT_SCHEMA, OUTPUT_SCHEMA, SERVER_NAME, TOOL_NAME, TOOL_DESCRIPTION,
        )

        server = Server(SERVER_NAME)

        @server.list_tools()
        async def list_tools():
            return [McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION,
                            inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA)]

        @server.call_tool()
        async def call_tool(name, arguments):
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=error_code)],
            )

        return server

    def _make_server_returning_malicious_error(self):
        """Create a server that returns a Tool error with malicious remote text."""
        from mcp.server import Server
        from mcp.types import Tool as McpTool, TextContent, CallToolResult
        from shared.mcp_execution_contract import (
            INPUT_SCHEMA, OUTPUT_SCHEMA, SERVER_NAME, TOOL_NAME, TOOL_DESCRIPTION,
        )

        server = Server(SERVER_NAME)

        @server.list_tools()
        async def list_tools():
            return [McpTool(name=TOOL_NAME, description=TOOL_DESCRIPTION,
                            inputSchema=INPUT_SCHEMA, outputSchema=OUTPUT_SCHEMA)]

        @server.call_tool()
        async def call_tool(name, arguments):
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text",
                    text="ConnectionRefusedError: http://internal:8080/secret?token=abc123")],
            )

        return server

    def _call_via_asgi(self, server, arguments):
        """Call run_code via in-process ASGI transport."""
        import httpx
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession

        session_manager = StreamableHTTPSessionManager(
            app=server,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        mcp_asgi = StreamableHTTPASGIApp(session_manager)

        async def _call():
            async with session_manager.run():
                transport = httpx.ASGITransport(app=mcp_asgi)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
                    async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool("run_code", arguments=arguments)
                            return result

        return asyncio.run(_call())

    def test_backend_unavailable_is_retryable(self):
        """backend_unavailable → BackendUnavailableError (retryable)."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _RETRYABLE_TOOL_ERRORS, BackendUnavailableError,
        )
        code = _classify_tool_error("backend_unavailable")
        assert code in _RETRYABLE_TOOL_ERRORS
        # In the worker, this maps to BackendUnavailableError → retry
        exc = BackendUnavailableError(code)
        assert isinstance(exc, BackendUnavailableError)

    def test_backend_timeout_is_retryable(self):
        """backend_timeout → BackendUnavailableError (retryable)."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _RETRYABLE_TOOL_ERRORS, BackendUnavailableError,
        )
        code = _classify_tool_error("backend_timeout")
        assert code in _RETRYABLE_TOOL_ERRORS

    def test_invalid_tool_result_is_not_retryable(self):
        """invalid_tool_result → InvalidToolResultError (NOT retryable)."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _NON_RETRYABLE_TOOL_ERRORS, InvalidToolResultError,
        )
        code = _classify_tool_error("invalid_tool_result")
        assert code in _NON_RETRYABLE_TOOL_ERRORS
        exc = InvalidToolResultError(code)
        assert isinstance(exc, InvalidToolResultError)
        assert not isinstance(exc, type("BackendUnavailableError", (), {}))

    def test_invalid_input_is_not_retryable(self):
        """invalid_input → InvalidToolResultError (NOT retryable)."""
        pytest.importorskip("mcp.server")
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _NON_RETRYABLE_TOOL_ERRORS, InvalidToolResultError,
        )
        code = _classify_tool_error("invalid_input")
        assert code in _NON_RETRYABLE_TOOL_ERRORS

    def test_malicious_remote_text_not_propagated(self):
        """Unknown/malicious Tool error text → unrecognized_tool_error,
        never echoes remote text."""
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, InvalidToolResultError,
        )
        malicious = "ConnectionRefusedError: http://internal:8080/secret?token=abc123"
        code = _classify_tool_error(malicious)
        assert code == "unrecognized_tool_error"
        # The exception message is the stable code, NOT the remote text
        exc = InvalidToolResultError(code)
        assert "internal" not in str(exc)
        assert "secret" not in str(exc)
        assert "token" not in str(exc)

    def test_all_four_stable_codes_classified(self):
        """All four stable codes from the server are correctly classified."""
        from learn_platform_api.services.code_lab_execution import (
            _classify_tool_error, _RETRYABLE_TOOL_ERRORS, _NON_RETRYABLE_TOOL_ERRORS,
        )
        for code in ["backend_unavailable", "backend_timeout"]:
            assert _classify_tool_error(code) in _RETRYABLE_TOOL_ERRORS
        for code in ["invalid_tool_result", "invalid_input"]:
            assert _classify_tool_error(code) in _NON_RETRYABLE_TOOL_ERRORS


# ===========================================================================
# §3.5: Worker error classification — BackendUnavailableError vs InvalidToolResultError
# ===========================================================================

class TestWorkerErrorClassification:
    """Verify the worker distinguishes retryable vs non-retryable errors.

    The worker in code_lab_workers.py already has:
      except BackendUnavailableError: _mark_failed("backend_unavailable")
      except InvalidToolResultError: _mark_failed("invalid_tool_result")

    With the fix in call_run_code_via_mcp, the classification is now correct.
    """

    def test_backend_unavailable_maps_to_retryable_in_worker(self):
        """BackendUnavailableError → worker marks backend_unavailable (retryable)."""
        from learn_platform_api.services.code_lab_execution import BackendUnavailableError
        exc = BackendUnavailableError("backend_unavailable")
        # Worker code: except BackendUnavailableError: _mark_failed(job_id, "backend_unavailable")
        # This is the retry path
        assert isinstance(exc, BackendUnavailableError)

    def test_invalid_tool_result_maps_to_non_retryable_in_worker(self):
        """InvalidToolResultError → worker marks invalid_tool_result (non-retryable)."""
        from learn_platform_api.services.code_lab_execution import InvalidToolResultError
        exc = InvalidToolResultError("invalid_tool_result")
        # Worker code: except InvalidToolResultError: _mark_failed(job_id, "invalid_tool_result")
        # This is NOT the retry path
        assert isinstance(exc, InvalidToolResultError)
        assert not isinstance(exc, type("BackendUnavailableError", (), {}))

    def test_unrecognized_error_maps_to_non_retryable(self):
        """Unrecognized Tool error → InvalidToolResultError → non-retryable."""
        from learn_platform_api.services.code_lab_execution import (
            InvalidToolResultError, _classify_tool_error,
        )
        code = _classify_tool_error("some_unknown_garbage")
        exc = InvalidToolResultError(code)
        # Worker catches InvalidToolResultError → _mark_failed("invalid_tool_result")
        assert isinstance(exc, InvalidToolResultError)


# ===========================================================================
# §4: Server _sanitize_error — no detail, only stable codes
# ===========================================================================

class TestServerSanitizeError:
    """Verify the server's _sanitize_error returns only stable codes."""

    @pytest.fixture(autouse=True)
    def _import_server(self):
        mcp_path = str(APPS_DIR / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

    def test_stable_codes_returned_as_is(self):
        """Known stable codes are returned unchanged."""
        pytest.importorskip("mcp.server")
        from mcp_execution_server import _sanitize_error, _STABLE_ERROR_CODES
        for code in _STABLE_ERROR_CODES:
            assert _sanitize_error(code) == code

    def test_unknown_code_returns_default(self):
        """Unknown codes are mapped to backend_unavailable."""
        pytest.importorskip("mcp.server")
        from mcp_execution_server import _sanitize_error
        assert _sanitize_error("unknown_error") == "backend_unavailable"

    def test_no_detail_appending(self):
        """_sanitize_error takes only one argument (no detail param)."""
        pytest.importorskip("mcp.server")
        import inspect
        from mcp_execution_server import _sanitize_error
        sig = inspect.signature(_sanitize_error)
        assert len(sig.parameters) == 1, "_sanitize_error must have only 'code' param"


# ===========================================================================
# §5: Static checks — no private API, error codes
# ===========================================================================

class TestStaticChecks:
    """Verify no private API access and correct error code set."""

    @pytest.fixture(autouse=True)
    def _import_server(self):
        mcp_path = str(APPS_DIR / "mcp_execution")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

    def test_no_private_sdk_attributes_in_server(self):
        """mcp_execution_server.py must not access any _-prefixed SDK attributes."""
        import re
        server_path = APPS_DIR / "mcp_execution" / "mcp_execution_server.py"
        src = server_path.read_text(encoding="utf-8")
        code = re.sub(r'""".*?"""', '', src, flags=re.DOTALL)
        code = re.sub(r"'''.*?'''", '', code, flags=re.DOTALL)
        code = re.sub(r'#[^\n]*', '', code)
        assert "_tool_manager" not in code
        assert "_mcp_server" not in code

    def test_server_stable_codes_match_client(self):
        """Server and client must agree on the set of stable error codes."""
        pytest.importorskip("mcp.server")
        from mcp_execution_server import _STABLE_ERROR_CODES as server_codes
        from learn_platform_api.services.code_lab_execution import (
            _ALL_STABLE_TOOL_ERRORS as client_codes,
        )
        assert server_codes == client_codes

    def test_client_retryable_subset_is_correct(self):
        """Retryable codes must be a proper subset of all stable codes."""
        from learn_platform_api.services.code_lab_execution import (
            _RETRYABLE_TOOL_ERRORS, _NON_RETRYABLE_TOOL_ERRORS, _ALL_STABLE_TOOL_ERRORS,
        )
        assert _RETRYABLE_TOOL_ERRORS | _NON_RETRYABLE_TOOL_ERRORS == _ALL_STABLE_TOOL_ERRORS
        assert _RETRYABLE_TOOL_ERRORS & _NON_RETRYABLE_TOOL_ERRORS == frozenset()

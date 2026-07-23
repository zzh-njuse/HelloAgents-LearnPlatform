"""Fake Wolfram MCP server for offline testing.

Per Correction 011 §2: enables testing of Lesson Writer science verification,
Practice science generation/grading, and Tutor science tool calls without
a real Wolfram account or remote service.

Exposes WolframAlpha and WolframContext tools with deterministic fake results.
Can be used via httpx.ASGITransport in tests, exactly like the existing
fake execution MCP server pattern in test_slice4_correction_008/009.
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool


# Fixed tool schemas matching what the real Wolfram MCP would expose
WOLFRAM_ALPHA_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "input": {"type": "string", "description": "Wolfram Alpha query string"},
        "podstate": {"type": "string", "description": "Optional pod state"},
    },
    "required": ["input"],
}

WOLFRAM_ALPHA_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
        "pods": {"type": "array", "items": {"type": "object"}},
    },
}

WOLFRAM_CONTEXT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Context query"},
        "context": {"type": "string", "description": "Context string"},
    },
    "required": ["query"],
}

WOLFRAM_CONTEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
    },
}


def create_fake_wolfram_server(
    *,
    call_count: list[int] | None = None,
    results: dict[str, dict] | None = None,
) -> Server:
    """Create a fake Wolfram MCP server for testing.

    Args:
        call_count: Optional mutable list to track call count.
        results: Optional dict mapping query strings to custom result dicts.

    Returns:
        An MCP Server instance that can be used with StreamableHTTPASGIApp.
    """
    server = Server("wolfram-cloud-mcp")

    if call_count is None:
        call_count = [0]

    if results is None:
        results = {}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="WolframAlpha",
                description="Wolfram Alpha computational knowledge engine",
                inputSchema=WOLFRAM_ALPHA_INPUT_SCHEMA,
            ),
            Tool(
                name="WolframContext",
                description="Wolfram contextual computation",
                inputSchema=WOLFRAM_CONTEXT_INPUT_SCHEMA,
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        call_count[0] += 1

        if name == "WolframAlpha":
            query = arguments.get("input", "")
            # Check for custom result
            if query in results:
                return [TextContent(type="text", text=json.dumps(results[query]))]
            # Default deterministic results for common test expressions
            if "x^2 = 4" in query or "x**2 = 4" in query:
                return [TextContent(type="text", text=json.dumps({"result": "x = -2, x = 2"}))]
            if "integrate" in query.lower() or "integral" in query.lower():
                return [TextContent(type="text", text=json.dumps({"result": "integrated result"}))]
            if "solve" in query.lower():
                return [TextContent(type="text", text=json.dumps({"result": "solution found"}))]
            if "derivative" in query.lower() or "diff" in query.lower():
                return [TextContent(type="text", text=json.dumps({"result": "derivative computed"}))]
            # Generic fake result
            return [TextContent(type="text", text=json.dumps({"result": f"computed: {query[:50]}"}))]

        if name == "WolframContext":
            query = arguments.get("query", "")
            if query in results:
                return [TextContent(type="text", text=json.dumps(results[query]))]
            return [TextContent(type="text", text=json.dumps({"result": f"context result: {query[:50]}"}))]

        # Unknown tool — should not happen since list_tools is fixed
        return [TextContent(type="text", text=json.dumps({"error": "unknown_tool"}))]

    return server


def create_fake_wolfram_app(
    *,
    call_count: list[int] | None = None,
    results: dict[str, dict] | None = None,
):
    """Create a full ASGI app with the fake Wolfram MCP server.

    Returns an ASGI app that can be used with httpx.ASGITransport
    for in-process testing, exactly like the execution MCP server.
    """
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    server = create_fake_wolfram_server(call_count=call_count, results=results)
    session_manager = StreamableHTTPSessionManager(server)
    return StreamableHTTPASGIApp(session_manager)

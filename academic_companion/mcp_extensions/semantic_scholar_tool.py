"""SemanticScholarTool — 通过 MCP 协议搜索 Semantic Scholar

使用 semantic-scholar-mcp (FujishigeTemma) 的 FastMCP 实例，
通过 hello_agents MCPClient 内存 transport 通信。

MCP Server 工具名: search_papers
覆盖全领域学术论文，含 IEEE、ACM、arXiv 等主要来源及引用数据。
"""

import asyncio
import time
from typing import Dict, Any

from hello_agents.tools.base import ToolParameter
from hello_agents.tools.response import ToolResponse
from hello_agents.tools.errors import ToolErrorCode

from academic_companion.mcp_extensions.base import McpToolBase


class SemanticScholarTool(McpToolBase):
    """Semantic Scholar 学术论文检索工具 (MCP 协议)

    搜索全领域学术论文，覆盖 IEEE、ACM、arXiv 等主要来源。
    返回论文元数据含引用计数、DOI、arXiv ID 等。

    内置 rate limiter: 无 API key 时全局共享限流，两次调用间隔 >= 2s。
    """

    mcp_server_module = "semantic_scholar_mcp"
    mcp_tool_name = "search_papers"
    tool_name = "SemanticScholar"
    tool_description = (
        "Semantic Scholar 学术论文检索。覆盖全领域 (含 IEEE、ACM、arXiv)，含引用数据。\n"
        "注意: 请一次给出全面的搜索词，避免短时间多次调用。\n"
        "参数:\n"
        "- query: 搜索查询 (必需)\n"
        "- max_results: 返回数量 1-20 (默认 10)\n"
        "- year_from: 起始年份 (可选, 如 \"2023\")"
    )

    tool_params = [
        ToolParameter(
            name="query",
            type="string",
            description="搜索查询，请一次给出涵盖所有相关方面的完整英文查询",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="返回结果数量，1-20",
            required=False,
            default=10,
        ),
        ToolParameter(
            name="year_from",
            type="string",
            description="起始年份，如 \"2023\"",
            required=False,
            default="",
        ),
    ]

    _initialized = False

    # Rate limiter: 两次调用间隔 >= 2s (无 API key 时共享限流)
    _last_call_time: float = 0.0
    _MIN_INTERVAL: float = 2.0

    @classmethod
    def _get_fastmcp_instance(cls):
        """获取 Semantic Scholar MCP Server 的 FastMCP 实例 (内存 transport)"""
        try:
            from semantic_scholar_mcp.server import mcp
            return mcp
        except ImportError:
            return None

    async def _ensure_initialized(self):
        """semantic-scholar-mcp 要求在调用工具前先 initialize_server()"""
        if not self.__class__._initialized:
            from semantic_scholar_mcp.server import initialize_server
            await initialize_server()
            self.__class__._initialized = True

    async def _arun(self, parameters: Dict[str, Any]) -> ToolResponse:
        await self._ensure_initialized()

        query = parameters.get("query", "")
        max_results = min(max(int(parameters.get("max_results", 10)), 1), 20)
        year_from = parameters.get("year_from", "")

        if not query.strip():
            return ToolResponse.error(
                code=ToolErrorCode.INVALID_PARAM,
                message="query 参数不能为空",
            )

        # Rate limiter
        elapsed = time.monotonic() - self.__class__._last_call_time
        if elapsed < self.__class__._MIN_INTERVAL:
            await asyncio.sleep(self.__class__._MIN_INTERVAL - elapsed)

        args: Dict[str, Any] = {"query": query, "limit": max_results}
        if year_from:
            args["year_from"] = year_from

        try:
            return await self._call_mcp_tool(args)
        finally:
            self.__class__._last_call_time = time.monotonic()

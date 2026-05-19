"""ArxivSearchTool — 通过 MCP 协议搜索 arXiv 预印本

使用 arxiv-search-mcp-server (gavinHuang) 的 FastMCP 实例，
通过 hello_agents MCPClient 内存 transport 通信。

MCP Server 工具名: search_arxiv_papers
实际参数: terms, subject, start_date, end_date, max_results
"""

import asyncio
import time
from typing import Dict, Any

from hello_agents.tools.base import ToolParameter
from hello_agents.tools.response import ToolResponse
from hello_agents.tools.errors import ToolErrorCode

from academic_companion.mcp_extensions.base import McpToolBase


class ArxivSearchTool(McpToolBase):
    """arXiv 预印本论文检索工具 (MCP 协议)

    从 arXiv.org 搜索 CS/AI/ML 等领域的预印本论文。

    内置 rate limiter: arXiv API 要求同一 IP 两次请求间隔 >= 3 秒。
    """

    mcp_server_module = "arxiv_search_mcp_server"
    mcp_tool_name = "search_arxiv_papers"
    tool_name = "ArxivSearch"
    tool_description = (
        "arXiv 预印本论文检索。从 arXiv.org 搜索 CS/AI/ML 等领域的预印本论文。\n"
        "注意: arXiv API 有限流，请一次给出全面的搜索词，避免短时间多次调用。\n"
        "参数:\n"
        "- query: 搜索关键词 (必需, 英文)\n"
        "- max_results: 返回数量 1-30 (默认 10)\n"
        "- subject: 限定学科领域 (可选, 如 \"cs\" 表示 CS 领域)"
    )

    tool_params = [
        ToolParameter(
            name="query",
            type="string",
            description="搜索查询，英文关键词。请一次给出涵盖所有相关方面的完整查询",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="返回结果数量，1-30",
            required=False,
            default=10,
        ),
        ToolParameter(
            name="subject",
            type="string",
            description="限定学科: cs/math/stat/q-bio/q-fin/econ/eess/physics 等",
            required=False,
            default="cs",
        ),
    ]

    # arXiv API rate limiter: 两次调用间隔 >= 3 秒
    _last_call_time: float = 0.0
    _MIN_INTERVAL: float = 3.5  # 留一点余量

    @classmethod
    def _get_fastmcp_instance(cls):
        """获取 arXiv MCP Server 的 FastMCP 实例 (内存 transport)"""
        try:
            from arxiv_search_mcp_server.server import mcp
            return mcp
        except ImportError:
            return None

    async def _arun(self, parameters: Dict[str, Any]) -> ToolResponse:
        query = parameters.get("query", "")
        max_results = min(max(int(parameters.get("max_results", 10)), 1), 30)
        subject = parameters.get("subject", "cs")

        if not query.strip():
            return ToolResponse.error(
                code=ToolErrorCode.INVALID_PARAM,
                message="query 参数不能为空",
            )

        # Rate limiter: 确保两次 arXiv API 调用间隔 >= 3.5s
        elapsed = time.monotonic() - self.__class__._last_call_time
        if elapsed < self.__class__._MIN_INTERVAL:
            wait = self.__class__._MIN_INTERVAL - elapsed
            await asyncio.sleep(wait)

        try:
            result = await self._call_mcp_tool({
                "terms": query,
                "max_results": max_results,
                "subject": subject,
            })
            return result
        finally:
            self.__class__._last_call_time = time.monotonic()

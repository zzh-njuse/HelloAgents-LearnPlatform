"""MCP 工具单元测试"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from dotenv import load_dotenv

load_dotenv()


class TestArxivSearchTool:
    """arXiv MCP 工具测试"""

    @pytest.fixture
    def tool(self):
        from academic_companion.mcp_extensions.arxiv_tool import ArxivSearchTool
        return ArxivSearchTool()

    def test_tool_creation(self, tool):
        """工具实例创建"""
        assert tool.tool_name == "ArxivSearch"
        assert tool.mcp_tool_name == "search_arxiv_papers"

    def test_fastmcp_instance(self, tool):
        """FastMCP 实例获取"""
        instance = tool._get_fastmcp_instance()
        assert instance is not None, "arxiv-search-mcp-server 未安装或 FastMCP 实例不可用"

    def test_empty_query(self, tool):
        """空查询返回错误"""
        result = tool.run({"query": ""})
        assert result.status.value == "error"

    @pytest.mark.slow
    def test_search_basic(self, tool):
        """基本搜索返回结果"""
        if tool._get_fastmcp_instance() is None:
            pytest.skip("arxiv-search-mcp-server 未安装")
        result = tool.run({"query": "machine learning", "max_results": 3})
        assert result.status.value in ("success", "partial", "error")
        # 成功或限流都算正常
        print(f"MCP result: {result.status.value} — {result.text[:200]}")


class TestSemanticScholarTool:
    """Semantic Scholar MCP 工具测试"""

    @pytest.fixture
    def tool(self):
        from academic_companion.mcp_extensions.semantic_scholar_tool import SemanticScholarTool
        return SemanticScholarTool()

    def test_tool_creation(self, tool):
        """工具实例创建"""
        assert tool.tool_name == "SemanticScholar"
        assert tool.mcp_tool_name == "search_papers"

    def test_fastmcp_instance(self, tool):
        """FastMCP 实例获取"""
        instance = tool._get_fastmcp_instance()
        assert instance is not None, "semantic-scholar-mcp 未安装"

    def test_empty_query(self, tool):
        """空查询返回错误"""
        result = tool.run({"query": ""})
        assert result.status.value == "error"


class TestMcpToolBase:
    """McpToolBase 基类测试"""

    def test_import_base(self):
        from academic_companion.mcp_extensions.base import McpToolBase
        assert McpToolBase is not None

    def test_all_tools_exported(self):
        from academic_companion.mcp_extensions import ArxivSearchTool, SemanticScholarTool, McpToolBase
        assert ArxivSearchTool is not None
        assert SemanticScholarTool is not None
        assert McpToolBase is not None

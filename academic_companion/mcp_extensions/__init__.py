"""MCP 扩展层 — 通过 MCP 协议调用外部学术搜索服务

架构:
  Agent Tool → McpToolBase → hello_agents.mcp.MCPClient (stdio transport)
    → 子进程 (arxiv-search-mcp-server / semantic-scholar-mcp)
      → 外部学术 API

McpToolBase 负责:
  1. sync/async 桥接 (MCPClient 是 async, Tool.run() 是 sync)
  2. MCPClient 生命周期管理 (连接/调用/断开)
  3. MCP 返回值 → ToolResponse 转换
  4. 错误处理和降级

子类只需声明 mcp_server_module / mcp_tool_name / tool_params 等属性即可。
"""

from academic_companion.mcp_extensions.base import McpToolBase
from academic_companion.mcp_extensions.arxiv_tool import ArxivSearchTool
from academic_companion.mcp_extensions.semantic_scholar_tool import SemanticScholarTool

__all__ = ["McpToolBase", "ArxivSearchTool", "SemanticScholarTool"]

"""MCP (Model Context Protocol) 子包

基于 fastmcp 库的封装，提供：
- MCPServer: 创建 MCP 服务器（需要 fastmcp）
- MCPClient: 连接 MCP 服务器（需要 fastmcp）
- create_context / parse_context: 上下文管理（无外部依赖）
"""

from .utils import create_context, parse_context, create_error_response, create_success_response

# 服务器需要 fastmcp
try:
    from .server import MCPServer, MCPServerBuilder, create_example_server
    MCP_SERVER_AVAILABLE = True
except ImportError:
    MCP_SERVER_AVAILABLE = False

    class MCPServer:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "MCP server requires the 'fastmcp' library. "
                "Install it with: pip install fastmcp"
            )

    MCPServerBuilder = MCPServer
    create_example_server = MCPServer


# 客户端需要 fastmcp
try:
    from .client import MCPClient
    MCP_CLIENT_AVAILABLE = True
except ImportError:
    MCP_CLIENT_AVAILABLE = False

    class MCPClient:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "MCP client requires the 'fastmcp' library. "
                "Install it with: pip install fastmcp"
            )


__all__ = [
    "MCPClient",
    "MCPServer",
    "MCPServerBuilder",
    "create_example_server",
    "create_context",
    "parse_context",
    "create_error_response",
    "create_success_response",
]

"""McpToolBase — MCP 协议工具的基类

处理 sync/async 桥接和 MCPClient 生命周期管理。
框架的 hello_agents.mcp.MCPClient 是 async 的，Tool.run() 是 sync 的，
McpToolBase 用 asyncio.run() 桥接两者。

子类只需声明类属性即可得到一个可用的 MCP Tool:
  - mcp_server_module: MCP 服务器的 Python 模块名
  - mcp_tool_name: MCP 服务器暴露的工具名
  - tool_name: 注册到 Agent 的工具名
  - tool_description: 工具描述
  - tool_params: 参数列表
"""

import asyncio
import sys
from typing import Dict, Any, List, Optional

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse, ToolStatus
from hello_agents.tools.errors import ToolErrorCode


class McpToolBase(Tool):
    """MCP 协议工具基类

    封装了 MCPClient 的连接、调用、错误处理、返回格式转换。
    子类覆盖 _arun() 或直接使用默认的 _call_mcp_tool() 即可。
    """

    # 子类需要覆盖的类属性
    mcp_server_module: str = ""       # MCP 服务器 Python 模块名, 如 "arxiv_search_mcp"
    mcp_tool_name: str = ""           # MCP 服务器暴露的工具名, 如 "search_arxiv_papers"
    tool_name: str = ""               # 注册到 Agent 的工具名
    tool_description: str = ""        # 工具描述
    tool_params: List[ToolParameter] = []  # 参数定义

    def __init__(self):
        super().__init__(
            name=self.tool_name,
            description=self.tool_description,
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return self.tool_params

    # === sync/async 桥接 ===

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        """同步入口 → 桥接到异步

        用 asyncio.run() 驱动 _arun()。
        如检测到已有运行中的 event loop，则抛出明确错误（此时应使用 arun()）。
        """
        try:
            # 检测是否已有运行中的 event loop
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    return ToolResponse.error(
                        code=ToolErrorCode.INTERNAL_ERROR,
                        message="MCP Tool 不支持在已有 event loop 的环境中同步调用，请使用 await tool.arun()",
                    )
            except RuntimeError:
                pass  # 没有运行中的 loop，正常使用 asyncio.run()

            return asyncio.run(self._arun(parameters))
        except Exception as e:
            return ToolResponse.error(
                code=ToolErrorCode.INTERNAL_ERROR,
                message=f"MCP 工具调用失败 ({self.tool_name}): {str(e)}",
            )

    async def arun(self, parameters: Dict[str, Any]) -> ToolResponse:
        """异步入口 → 直接 await，不走 asyncio.run()"""
        try:
            return await self._arun(parameters)
        except Exception as e:
            return ToolResponse.error(
                code=ToolErrorCode.INTERNAL_ERROR,
                message=f"MCP 工具调用失败 ({self.tool_name}): {str(e)}",
            )

    async def _arun(self, parameters: Dict[str, Any]) -> ToolResponse:
        """子类覆盖此方法实现具体的 MCP 调用逻辑"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须覆盖 _arun() 方法"
        )

    # === MCP 调用封装 ===

    @classmethod
    def _get_fastmcp_instance(cls):
        """子类可覆盖，返回 FastMCP 实例以使用内存 transport（免子进程启动开销）。

        Returns None 表示使用 stdio transport（默认）。
        """
        return None

    async def _call_mcp_tool(
        self,
        arguments: Dict[str, Any],
        *,
        server_module: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> ToolResponse:
        """通用 MCP 调用 → 返回 ToolResponse

        支持两种 transport:
          1. 内存 transport: 子类覆盖 _get_fastmcp_instance() 返回 FastMCP 实例
          2. stdio transport: 默认，启动 python -m {module} 子进程

        Args:
            arguments: 传给 MCP 工具的参数字典
            server_module: 覆盖默认的 mcp_server_module（仅 stdio 模式）
            tool_name: 覆盖默认的 mcp_tool_name

        Returns:
            ToolResponse (success / error)
        """
        from hello_agents.mcp.client import MCPClient

        module = server_module or self.mcp_server_module
        tname = tool_name or self.mcp_tool_name

        try:
            # 优先尝试内存 transport（子类提供了 FastMCP 实例）
            fastmcp_instance = self._get_fastmcp_instance()
            if fastmcp_instance is not None:
                server_source = fastmcp_instance
            else:
                server_source = [sys.executable, "-m", module]

            async with MCPClient(
                server_source=server_source,
                transport_type="stdio" if fastmcp_instance is None else None,
            ) as client:
                # 健康检查
                if not await client.ping():
                    return ToolResponse.error(
                        code=ToolErrorCode.NETWORK_ERROR,
                        message=f"无法连接到 MCP 服务器: {module}",
                    )

                # 调用 MCP 工具
                result = await client.call_tool(tname, arguments)

                return self._parse_mcp_result(result, tname, arguments)

        except ImportError as e:
            return ToolResponse.error(
                code=ToolErrorCode.INTERNAL_ERROR,
                message=f"fastmcp 库未安装，无法使用 MCP 工具: {str(e)}",
            )
        except Exception as e:
            return ToolResponse.error(
                code=ToolErrorCode.NETWORK_ERROR,
                message=f"MCP 调用异常 ({module}/{tname}): {str(e)}",
            )

    def _parse_mcp_result(
        self,
        result: Any,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> ToolResponse:
        """将 MCP 调用结果转为 ToolResponse

        MCPClient.call_tool() 返回:
          - str: 单个文本内容
          - List[str]: 多个内容
          - None: 无内容

        子类可覆盖此方法做自定义解析。
        """
        if result is None:
            return ToolResponse.success(
                text="MCP 工具调用完成，无返回内容。",
                data={"tool": tool_name, "arguments": arguments or {}},
            )

        if isinstance(result, str):
            return ToolResponse.success(
                text=result,
                data={"tool": tool_name, "arguments": arguments or {}, "raw": result},
            )

        if isinstance(result, list):
            text = "\n\n".join(str(item) for item in result)
            return ToolResponse.success(
                text=text,
                data={"tool": tool_name, "arguments": arguments or {}, "raw": result},
            )

        # 未知格式，尝试转字符串
        return ToolResponse.success(
            text=str(result),
            data={"tool": tool_name, "arguments": arguments or {}, "raw": str(result)},
        )

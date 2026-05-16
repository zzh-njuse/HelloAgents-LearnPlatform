"""WebSearch Fallback 工具

当 RAG 知识库检索未命中时，fallback 到外部搜索。
MVP 版本使用 Tavily Search API（免费 tier: 1000 searches/month）。
后续可切换为其他搜索引擎或 MCP 协议。
"""

from typing import Dict, Any, List
from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse
from hello_agents.tools.errors import ToolErrorCode


class WebSearchFallbackTool(Tool):
    """网络搜索 Fallback 工具

    当 RAG 检索结果相关性不足时，自动 fallback 到外部搜索。
    支持 Tavily Search API 或 SerpAPI。

    环境变量:
    - TAVILY_API_KEY: Tavily API Key (推荐)
    - 或 SERPAPI_API_KEY: SerpAPI Key (备选)
    """

    def __init__(self):
        super().__init__(
            name="WebSearch",
            description="""当知识库中没有相关内容时，搜索互联网获取信息。

返回: 搜索结果摘要和来源链接。
搜索范围: CS 技术博客、官方文档、Stack Overflow 等。

参数:
- query: 搜索查询（必需）
- num_results: 返回结果数（1-10，默认 3）""",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索查询",
                required=True,
            ),
            ToolParameter(
                name="num_results",
                type="integer",
                description="返回结果数 1-10，默认 3",
                required=False,
                default=3,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        query = parameters.get("query", "")
        num = min(max(int(parameters.get("num_results", 3)), 1), 10)

        if not query.strip():
            return ToolResponse.error(
                code=ToolErrorCode.INVALID_PARAM,
                message="query 参数不能为空",
            )

        # 尝试 Tavily API
        result = self._try_tavily(query, num)
        if result is not None:
            return result

        # Fallback: 返回提示
        return ToolResponse.partial(
            text=f"网络搜索暂不可用。请确保设置了 TAVILY_API_KEY 环境变量。\n"
                 f"获取免费 API Key: https://tavily.com/\n\n"
                 f"你可以尝试: (1) 换个关键词重新搜索 RAG 知识库 "
                 f"(2) 手动搜索: https://www.google.com/search?q={query.replace(' ', '+')}",
            data={
                "query": query,
                "fallback_url": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            },
        )

    def _try_tavily(self, query: str, num: int):
        """尝试使用 Tavily Search API"""
        try:
            import os
            api_key = os.getenv("TAVILY_API_KEY")
            if not api_key:
                return None

            import requests
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": num,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return ToolResponse.success(
                    text=f"搜索完成，但未找到与 '{query}' 相关的结果。",
                    data={"query": query, "results_count": 0},
                )

            # 格式化结果
            lines = [f"搜索: {query}\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Untitled")
                content = r.get("content", "")[:300]
                url = r.get("url", "")
                lines.append(f"[{i}] {title}")
                lines.append(f"    {content}")
                if url:
                    lines.append(f"    URL: {url}")
                lines.append("")

            return ToolResponse.success(
                text="\n".join(lines),
                data={
                    "query": query,
                    "results_count": len(results),
                    "source": "tavily",
                },
            )
        except Exception:
            return None

"""RAG 检索 Tool — 将 RAG RetrievalPipeline 注册为 Agent 可调用的工具"""

from typing import Dict, Any, List
from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse
from hello_agents.rag.pipeline import (
    create_rag_pipeline,
    search_vectors_expanded,
    rerank_with_cross_encoder,
    merge_snippets_grouped,
)
from academic_companion.config import get_config


class RAGRetrievalTool(Tool):
    """RAG 知识库检索工具

    从向量数据库中检索 CS 八股和 LeetCode 题解知识。
    支持语义搜索、多查询扩展（MQE）和假设文档（HyDE）增强。

    使用示例:
        >>> tool = RAGRetrievalTool()
        >>> result = tool.run({"query": "TCP 三次握手的过程"})
        >>> print(result.text)
    """

    def __init__(self):
        super().__init__(
            name="RAGRetrieval",
            description="""从知识库中检索 CS 面试八股和算法题解。

支持查询: 操作系统、计算机网络、数据库、算法模式、LeetCode 题目等。
返回: 带来源引用的检索结果摘要。

参数:
- query: 搜索查询（必需）
- top_k: 返回结果数（1-20，默认 5）
- topic: 限定知识领域（可选: os/network/database/algorithm/leetcode）
- source_dir: 限定文件目录（如 mysql/index），用于章节范围检索""",
            expandable=False,
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索查询，可以是自然语言问题或关键词",
                required=True,
            ),
            ToolParameter(
                name="top_k",
                type="integer",
                description="返回结果数量，1-20，默认 5",
                required=False,
                default=5,
            ),
            ToolParameter(
                name="topic",
                type="string",
                description="限定知识领域: os/network/database/algorithm/leetcode，留空则搜索全部",
                required=False,
                default="",
            ),
            ToolParameter(
                name="source_dir",
                type="string",
                description="限定文件目录路径（如 mysql/index），留空则不限制",
                required=False,
                default="",
            ),
        ]

    def _build_search_query(self, query: str, topic: str = "") -> str:
        """根据 topic 增强查询"""
        topic_keywords = {
            "os": "操作系统",
            "network": "计算机网络 TCP IP",
            "database": "数据库 索引 SQL",
            "algorithm": "算法 数据结构",
            "leetcode": "LeetCode 算法题",
        }
        if topic and topic in topic_keywords:
            return f"{topic_keywords[topic]} {query}"
        return query

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        query = parameters.get("query", "")
        topic = parameters.get("topic", "")
        top_k = min(max(int(parameters.get("top_k", 5)), 1), 20)
        source_dir = parameters.get("source_dir", "")

        if not query.strip():
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="query 参数不能为空",
            )

        config = get_config()

        try:
            # 增强查询
            search_query = self._build_search_query(query, topic)

            # 直接使用 Qdrant 检索，绕开 pipeline 的旧 filter（memory_type 等字段不被新版 Qdrant Cloud 兼容）
            from hello_agents.storage.qdrant_store import QdrantVectorStore
            from hello_agents.embedding import get_text_embedder

            store = QdrantVectorStore()
            embedder = get_text_embedder()
            query_vector = embedder.embed([search_query])[0]

            # Qdrant payload filter（按章节 source_dir 过滤）
            sc_filter = None
            if source_dir:
                sc_filter = {
                    "must": [
                        {"key": "source_path", "match": {"text": source_dir}}
                    ]
                }

            all_results = []

            # 搜索 CS 知识库
            cs_results = store.search_similar(
                query_vector=query_vector,
                top_k=top_k,
                score_threshold=config.rag.score_threshold,
                collection_name=config.rag.collection_cs,
                filter_conditions=sc_filter,
            )
            all_results.extend(cs_results)

            # 搜索 LeetCode 题库
            lc_results = store.search_similar(
                query_vector=query_vector,
                top_k=max(3, top_k // 2),
                score_threshold=config.rag.score_threshold,
                collection_name=config.rag.collection_leetcode,
                filter_conditions=sc_filter,
            )
            all_results.extend(lc_results)

            # 去重 + 按分数排序
            seen_ids = set()
            unique = []
            for r in sorted(all_results, key=lambda x: x["score"], reverse=True):
                rid = r.get("id", r.get("metadata", {}).get("problem_id", ""))
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    unique.append(r)
            hits = unique[:top_k]

            if not hits:
                return ToolResponse.partial(
                    text="知识库中未找到相关内容。可能的原因：(1) 知识库尚未包含该领域数据 (2) 查询与已有内容差异较大",
                    data={"hits_count": 0, "fallback_recommended": True},
                )

            # 格式化结果
            lines = [f"检索结果 ({len(hits)} 条):\n"]
            for i, h in enumerate(hits, 1):
                md = h.get("metadata", {})
                src = md.get("source", md.get("filename", md.get("title", "?")))
                content = md.get("content", "")
                if not content and "content" in h:
                    content = h["content"]
                snippet = str(content)[:400] if content else ""
                lines.append(f"[{i}] {src}  (score={h['score']:.3f})")
                lines.append(f"    {snippet}\n")

            merged = "\n".join(lines)

            return ToolResponse.success(
                text=merged,
                data={
                    "hits_count": len(hits),
                    "query_used": search_query,
                    "topic_filter": topic or "all",
                },
            )

        except Exception as e:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"RAG 检索失败: {str(e)}",
            )

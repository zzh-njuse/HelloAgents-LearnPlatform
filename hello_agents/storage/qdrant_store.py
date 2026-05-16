"""Qdrant 向量存储封装

提供 Qdrant HTTP 客户端的单例管理和向量 CRUD 操作。
从环境变量 QDRANT_URL / QDRANT_API_KEY 初始化连接。
"""

import os
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger("hello_agents.storage.qdrant")


class QdrantConnectionManager:
    """Qdrant 连接管理器（单例模式）

    从环境变量读取配置:
    - QDRANT_URL: Qdrant 服务地址（默认 http://localhost:6333）
    - QDRANT_API_KEY: API 密钥（可选）
    """

    _instance: Optional["QdrantConnectionManager"] = None

    def __new__(cls, url: str = None, api_key: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, url: str = None, api_key: str = None):
        if self._initialized:
            return
        self._initialized = True
        self._url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self._api_key = api_key or os.environ.get("QDRANT_API_KEY")
        self._client = None

    @property
    def client(self):
        """延迟创建 Qdrant HTTP 客户端"""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError:
                raise ImportError(
                    "Qdrant client requires 'qdrant-client'. "
                    "Install it with: pip install qdrant-client"
                )
            kwargs = {"url": self._url}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = QdrantClient(**kwargs)
            logger.info("Qdrant client connected to %s", self._url)
        return self._client

    def reset(self):
        """重置连接（用于测试或配置变更后）"""
        self._client = None


class QdrantVectorStore:
    """Qdrant 向量存储

    封装向量和元数据的批量写入、相似搜索、集合管理等操作。

    使用示例:
        >>> store = QdrantVectorStore()
        >>> store.ensure_collection("my_docs", dimension=1024)
        >>> store.add_vectors(
        ...     vectors=[[0.1, 0.2, ...], [0.3, 0.4, ...]],
        ...     metadatas=[{"source": "a"}, {"source": "b"}],
        ...     ids=["id1", "id2"],
        ...     collection_name="my_docs",
        ... )
        >>> results = store.search_similar(
        ...     query_vector=[0.15, 0.25, ...],
        ...     top_k=5,
        ...     collection_name="my_docs",
        ... )
    """

    def __init__(
        self,
        url: str = None,
        api_key: str = None,
        collection_name: str = "hello_agents_rag_vectors",
        vector_size: int = None,
        distance: str = "cosine",
    ):
        self._conn = QdrantConnectionManager(url=url, api_key=api_key)

    @property
    def client(self):
        return self._conn.client

    def ensure_collection(
        self,
        collection_name: str,
        dimension: int,
        distance: str = "cosine",
    ) -> None:
        """确保集合存在，不存在则创建

        Args:
            collection_name: 集合名称
            dimension: 向量维度
            distance: 距离度量 ("cosine" 或 "dot")
        """
        from qdrant_client.models import Distance, VectorParams

        try:
            self.client.get_collection(collection_name)
        except Exception:
            dist = Distance.COSINE if distance == "cosine" else Distance.DOT
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=dist),
            )
            logger.info("Created Qdrant collection '%s' (dim=%d, dist=%s)", collection_name, dimension, distance)

    def add_vectors(
        self,
        vectors: List[List[float]],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        collection_name: str = "hello_agents_rag_vectors",
    ) -> None:
        """批量写入向量和元数据

        Args:
            vectors: 向量列表
            metadatas: 每个向量对应的元数据
            ids: 每个向量的唯一 ID
            collection_name: 目标集合

        Raises:
            ValueError: 参数长度不一致
        """
        if len(vectors) != len(metadatas) or len(vectors) != len(ids):
            raise ValueError(
                f"Length mismatch: vectors={len(vectors)}, metadatas={len(metadatas)}, ids={len(ids)}"
            )

        from qdrant_client.models import PointStruct

        # 自动推断维度
        dimension = len(vectors[0]) if vectors else 0
        self.ensure_collection(collection_name, dimension)

        points = [
            PointStruct(id=id_, vector=vec, payload=meta)
            for id_, vec, meta in zip(ids, vectors, metadatas)
        ]

        # 分批写入（每批最多 1000 条）
        batch_size = 1000
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(collection_name=collection_name, points=batch)

    def search_similar(
        self,
        query_vector: List[float],
        top_k: int = 8,
        limit: int = None,  # 兼容旧 API (alias for top_k)
        where: Dict[str, Any] = None,  # 兼容旧 API (alias for filter_conditions)
        filter_conditions: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        collection_name: str = "hello_agents_rag_vectors",
    ) -> List[Dict[str, Any]]:
        """相似向量搜索"""
        if limit is not None:
            top_k = limit
        if where is not None:
            filter_conditions = where
        search_kwargs = {
            "collection_name": collection_name,
            "query": query_vector,
            "limit": top_k,
        }
        if filter_conditions:
            search_kwargs["query_filter"] = filter_conditions
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold

        results = self.client.query_points(**search_kwargs)

        return [
            {
                "id": hit.id,
                "score": hit.score,
                "metadata": hit.payload or {},
            }
            for hit in results.points
        ]

    def get_collection_stats(self, collection_name: str = "hello_agents_rag_vectors") -> Dict[str, Any]:
        """获取集合统计信息

        Args:
            collection_name: 集合名称

        Returns:
            统计字典 (points_count, vectors_count, indexed_vectors_count 等)
        """
        try:
            info = self.client.get_collection(collection_name)
            return {
                "name": collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "indexed_vectors_count": info.indexed_vectors_count,
            }
        except Exception:
            return {"name": collection_name, "error": "Collection not found"}

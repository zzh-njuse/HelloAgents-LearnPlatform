"""基于 sentence-transformers 的本地 Embedding 模型"""

from typing import List, Optional
import numpy as np

from .base import EmbeddingModel


class LocalTransformerEmbedding(EmbeddingModel):
    """基于 sentence-transformers 的本地 Transformer Embedding

    支持所有 sentence-transformers 兼容模型。
    内置内存缓存，相同文本不重复计算。

    使用示例:
        >>> embedder = LocalTransformerEmbedding("BAAI/bge-large-zh-v1.5")
        >>> vectors = embedder.embed(["你好世界", "Hello world"])
        >>> len(vectors[0])
        1024
    """

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", device: str = "cpu"):
        """
        Args:
            model_name: HuggingFace 模型名或本地路径
            device: 设备 ("cpu" 或 "cuda")
        """
        self.model_name = model_name
        self.device = device
        self._model = None
        self._cache: dict = {}

    @property
    def model(self):
        """延迟加载模型"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dimension(self) -> int:
        """获取 embedding 维度（不加载模型时的预估值）"""
        # 常见模型的维度映射
        known_dimensions = {
            "bge-large-zh": 1024,
            "bge-large": 1024,
            "bge-base-zh": 768,
            "bge-base": 768,
            "bge-small-zh": 512,
            "bge-small": 512,
            "all-MiniLM-L6": 384,
            "all-mpnet-base": 768,
            "multilingual-e5-large": 1024,
            "multilingual-e5-base": 768,
        }
        name_lower = self.model_name.lower()
        for key, dim in known_dimensions.items():
            if key.lower() in name_lower:
                return dim
        # 兜底：尝试加载模型获取维度
        return self.model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        """将文本列表转换为向量列表

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量为 float 列表
        """
        if not texts:
            return []

        # 检查缓存
        uncached_texts = []
        uncached_indices = []
        results = [None] * len(texts)

        for i, text in enumerate(texts):
            if text in self._cache:
                results[i] = self._cache[text]
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        if uncached_texts:
            embeddings = self.model.encode(
                uncached_texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            # 转为 Python list
            if isinstance(embeddings, np.ndarray):
                embeddings = embeddings.tolist()

            for idx, emb in zip(uncached_indices, embeddings):
                results[idx] = emb
                self._cache[texts[idx]] = emb

        return results

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()

    def encode(self, texts, **kwargs):
        """alias for embed() — compatibility with sentence-transformers API"""
        return self.embed(texts)

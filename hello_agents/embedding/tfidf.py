"""TF-IDF Sparse Embedding（fallback 用）

当 sentence-transformers 不可用时，使用 TF-IDF 作为替代方案。
适合 BM25 / 关键词搜索场景。
"""

from typing import List
import numpy as np

from .base import EmbeddingModel


class TFIDFEmbedding(EmbeddingModel):
    """基于 TF-IDF 的稀疏向量 Embedding

    使用 sklearn TfidfVectorizer 进行中文/英文分词和向量化。
    适合作为 sentence-transformers 不可用时的 fallback。

    使用示例:
        >>> embedder = TFIDFEmbedding(max_features=1024)
        >>> embedder.fit(["这是第一篇文档", "这是第二篇文档"])
        >>> vectors = embedder.embed(["新查询文本"])
        >>> len(vectors[0])
        1024
    """

    def __init__(self, max_features: int = 1024):
        """
        Args:
            max_features: TF-IDF 最大特征数（即向量维度）
        """
        self.max_features = max_features
        self._vectorizer = None
        self._fitted = False

    @property
    def vectorizer(self):
        """延迟加载 TfidfVectorizer"""
        if self._vectorizer is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                token_pattern=r"(?u)\b\w+\b",  # 兼容中英文
            )
        return self._vectorizer

    @property
    def dimension(self) -> int:
        return self.max_features

    def fit(self, corpus: List[str]):
        """用语料库训练 TF-IDF 词汇表

        Args:
            corpus: 文档列表，用于构建词汇表
        """
        self.vectorizer.fit(corpus)
        self._fitted = True

    def embed(self, texts: List[str]) -> List[List[float]]:
        """将文本列表转换为稀疏向量列表

        Args:
            texts: 文本列表

        Returns:
            向量列表（密集表示，填充到 max_features 维度）
        """
        if not texts:
            return []

        if not self._fitted:
            # 用当前文本就地 fit（临时方案）
            self.fit(texts)

        # TF-IDF 返回稀疏矩阵，转为密集列表
        sparse_matrix = self.vectorizer.transform(texts)
        dense = sparse_matrix.toarray()
        # 填充/截断到 max_features 维度
        result = []
        for row in dense:
            vec = row.tolist()
            if len(vec) < self.max_features:
                vec.extend([0.0] * (self.max_features - len(vec)))
            else:
                vec = vec[: self.max_features]
            result.append(vec)

        return result

    def clear(self):
        """重置 TF-IDF 状态"""
        self._vectorizer = None
        self._fitted = False

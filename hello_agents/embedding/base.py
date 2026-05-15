"""Embedding 抽象基类"""

from abc import ABC, abstractmethod
from typing import List


class EmbeddingModel(ABC):
    """Embedding 模型抽象基类

    所有 embedding 实现需继承此类，实现 embed() 方法和 dimension 属性。
    """

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """将文本列表转换为向量列表

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量为 float 列表
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回 embedding 向量的维度"""
        ...

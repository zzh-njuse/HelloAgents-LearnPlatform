"""Embedding 子包

提供统一的 Embedding 抽象层，支持：
- LocalTransformerEmbedding: 基于 sentence-transformers 的本地模型
- TFIDFEmbedding: 基于 sklearn 的 TF-IDF fallback
- 全局单例 embedder (get_text_embedder)
- 自动 fallback 机制 (create_embedding_model_with_fallback)
"""

from .base import EmbeddingModel
from .local import LocalTransformerEmbedding
from .tfidf import TFIDFEmbedding
from .factory import (
    create_embedding_model,
    create_embedding_model_with_fallback,
    get_text_embedder,
    get_dimension,
)

# 向后兼容别名
SentenceTransformerEmbedding = LocalTransformerEmbedding
HuggingFaceEmbedding = LocalTransformerEmbedding

__all__ = [
    "EmbeddingModel",
    "LocalTransformerEmbedding",
    "SentenceTransformerEmbedding",
    "HuggingFaceEmbedding",
    "TFIDFEmbedding",
    "create_embedding_model",
    "create_embedding_model_with_fallback",
    "get_text_embedder",
    "get_dimension",
]

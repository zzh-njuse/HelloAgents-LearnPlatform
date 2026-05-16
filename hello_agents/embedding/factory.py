"""Embedding 工厂函数 — 负责创建和管理全局 embedder 实例"""

from typing import Optional
from .base import EmbeddingModel
from .local import LocalTransformerEmbedding
from .tfidf import TFIDFEmbedding

# 全局单例
_global_embedder: Optional[EmbeddingModel] = None


def create_embedding_model(
    model_name: str = "BAAI/bge-large-zh-v1.5",
    device: str = "cpu",
    **kwargs,
) -> EmbeddingModel:
    """创建 Embedding 模型实例

    优先使用 LocalTransformerEmbedding (sentence-transformers)。
    如果 sentence-transformers 不可用，自动 fallback 到 TFIDF。

    Args:
        model_name: sentence-transformers 模型名或本地路径
        device: 设备 ("cpu" 或 "cuda")
        **kwargs: 额外参数（例如 max_features 传递给 TFIDF）

    Returns:
        EmbeddingModel 实例
    """
    return create_embedding_model_with_fallback(model_name, device, **kwargs)


def create_embedding_model_with_fallback(
    model_name: str = "BAAI/bge-large-zh-v1.5",
    device: str = "cpu",
    max_features: int = 1024,
) -> EmbeddingModel:
    """创建 Embedding 模型（带 fallback）

    尝试顺序:
    1. sentence-transformers (LocalTransformerEmbedding)
    2. TF-IDF (TFIDFEmbedding) — fallback

    Args:
        model_name: sentence-transformers 模型名
        device: 设备
        max_features: TF-IDF 最大特征数（仅在 fallback 时使用）

    Returns:
        EmbeddingModel 实例
    """
    # 尝试 1: sentence-transformers
    try:
        import sentence_transformers  # noqa: F401
        return LocalTransformerEmbedding(model_name, device)
    except ImportError:
        pass

    # 尝试 2: TF-IDF fallback
    try:
        embedder = TFIDFEmbedding(max_features=max_features)
        return embedder
    except ImportError:
        raise ImportError(
            "No embedding backend available. "
            "Install one of: pip install sentence-transformers  OR  pip install scikit-learn"
        )


def get_text_embedder() -> EmbeddingModel:
    """获取全局单例 embedder

    首次调用时自动创建（优先 sentence-transformers，fallback TF-IDF）。
    后续调用返回已创建的实例。

    Returns:
        全局 EmbeddingModel 实例
    """
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = create_embedding_model_with_fallback()
    return _global_embedder


def get_dimension(default: int = 384) -> int:
    """获取当前全局 embedder 的向量维度

    Args:
        default: 全局 embedder 未初始化时的默认维度
    """
    try:
        return get_text_embedder().dimension
    except Exception:
        return default

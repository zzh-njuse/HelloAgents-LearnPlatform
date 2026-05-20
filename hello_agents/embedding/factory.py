"""Embedding 工厂函数 — 命名注册表，支持不同子系统使用不同模型

用法:
    # RAG / ingestion → 大模型高精度
    embedder = get_text_embedder("rag")

    # Memory / 轻量查询 → 小模型低延迟
    embedder = get_text_embedder("memory")

    # 向后兼容
    embedder = get_text_embedder()  # → "default"
"""

import os
from typing import Dict, Optional
from .base import EmbeddingModel
from .local import LocalTransformerEmbedding
from .tfidf import TFIDFEmbedding

# 命名注册表：一个进程可同时持有多个 embedder 实例
_registry: Dict[str, EmbeddingModel] = {}


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


def _resolve_model_name(name: str) -> str:
    """根据 embedder 名称解析模型名（读环境变量）"""
    env_map = {
        "memory": "EMBED_MEMORY_MODEL",
        "rag": "EMBED_RAG_MODEL",
    }
    env_key = env_map.get(name, "EMBED_RAG_MODEL")
    return os.getenv(env_key, "BAAI/bge-large-zh-v1.5")


def get_text_embedder(name: str = "default") -> EmbeddingModel:
    """获取命名的 embedder 实例（首次调用时创建并缓存）

    不同子系统用不同的 name，各自独立，互不干扰：
    - "default" / "rag"  → EMBED_RAG_MODEL     (默认 bge-large, 1024维)
    - "memory"           → EMBED_MEMORY_MODEL   (默认 bge-large, 1024维)

    向后兼容：无参数调用等同 get_text_embedder("default")，走 EMBED_RAG_MODEL。
    """
    if name not in _registry:
        model_name = _resolve_model_name(name)
        _registry[name] = create_embedding_model_with_fallback(model_name=model_name)
    return _registry[name]


def reset_text_embedder(name: str = "default"):
    """重置某个命名的 embedder（ingestion 脚本用）"""
    _registry.pop(name, None)


def get_dimension(default: int = 384, name: str = "default") -> int:
    """获取指定 embedder 的向量维度

    Args:
        default: embedder 未初始化时的默认维度
        name: embedder 名称
    """
    try:
        return get_text_embedder(name).dimension
    except Exception:
        return default

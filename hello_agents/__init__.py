"""
HelloAgents - 灵活、可扩展的多智能体框架

基于OpenAI原生API构建，提供简洁高效的智能体开发体验。
"""

# 配置第三方库的日志级别，减少噪音
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

from .version import __version__, __author__, __email__, __description__

# 核心组件
from .core.llm import HelloAgentsLLM
from .core.config import Config
from .core.message import Message
from .core.exceptions import HelloAgentsException

# Agent实现
from .agents.simple_agent import SimpleAgent
from .agents.react_agent import ReActAgent
from .agents.reflection_agent import ReflectionAgent
from .agents.plan_solve_agent import PlanSolveAgent
PlanAndSolveAgent = PlanSolveAgent  # 向后兼容别名

# 工具系统
from .tools.registry import ToolRegistry, global_registry
from .tools.builtin.calculator import CalculatorTool, calculate

# Embedding 和 Storage（轻量，直接导入）
from .embedding import (
    EmbeddingModel,
    LocalTransformerEmbedding,
    TFIDFEmbedding,
    create_embedding_model,
    create_embedding_model_with_fallback,
    get_text_embedder,
    get_dimension,
)
from .storage import QdrantVectorStore, QdrantConnectionManager


def get_rag_pipeline():
    """获取 RAG Pipeline 工厂函数（延迟导入，避免强制依赖 Qdrant/sentence-transformers）"""
    from .rag import create_rag_pipeline
    return create_rag_pipeline


def get_mcp():
    """获取 MCP Client/Server 类（延迟导入，避免强制依赖 fastmcp）"""
    from .mcp import MCPClient, MCPServer
    return MCPClient, MCPServer


__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    "__email__",
    "__description__",

    # 核心组件
    "HelloAgentsLLM",
    "Config",
    "Message",
    "HelloAgentsException",

    # Agent范式
    "SimpleAgent",
    "ReActAgent",
    "ReflectionAgent",
    "PlanSolveAgent",
    "PlanAndSolveAgent",  # 向后兼容

    # 工具系统
    "ToolRegistry",
    "global_registry",
    "CalculatorTool",
    "calculate",

    # Embedding
    "EmbeddingModel",
    "LocalTransformerEmbedding",
    "TFIDFEmbedding",
    "create_embedding_model",
    "create_embedding_model_with_fallback",
    "get_text_embedder",
    "get_dimension",

    # Storage
    "QdrantVectorStore",
    "QdrantConnectionManager",

    # RAG (lazy)
    "get_rag_pipeline",

    # MCP (lazy)
    "get_mcp",
]


"""RAG (Retrieval-Augmented Generation) 子包

提供完整的 RAG 管线：
- document: Document / DocumentProcessor 数据模型和文档处理
- pipeline: IngestionPipeline / RetrievalPipeline / QueryPipeline
"""

from .document import Document, DocumentChunk, DocumentProcessor
from .pipeline import create_rag_pipeline

__all__ = [
    "Document",
    "DocumentChunk",
    "DocumentProcessor",
    "create_rag_pipeline",
]

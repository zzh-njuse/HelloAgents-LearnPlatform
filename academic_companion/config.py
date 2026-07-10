"""Academic AI Companion 统一配置

所有配置从环境变量读取，与 hello_agents 框架共享 .env 文件。
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RAGConfig:
    """RAG 检索配置"""
    collection_cs: str = "cs_fundamentals"
    collection_leetcode: str = "leetcode"
    top_k: int = 8
    score_threshold: float = 0.3
    enable_hyde: bool = False
    enable_mqe: bool = False
    max_chars: int = 3000
    include_citations: bool = True


@dataclass
class LearningModeConfig:
    """学习模式 Agent 配置"""
    temperature: float = 0.5
    max_tokens: int = 4096
    max_steps: int = 8
    # 教学风格
    teaching_style: str = "adaptive"  # adaptive | beginner | advanced
    # 四步教学法: concept → principle → example → exercise
    enable_exercises: bool = True


@dataclass
class MemoryConfig:
    """用户记忆配置"""
    persistence_dir: str = "memory"
    user_model_file: str = "memory/user_model.json"
    review_interval_days: int = 3  # 间隔重复周期
    weak_topic_threshold: float = 0.5  # 低于此掌握度标记为薄弱


@dataclass
class MCPConfig:
    """MCP 协议配置"""
    arxiv_server_module: str = "arxiv_search_mcp"
    semantic_scholar_server_module: str = "semantic_scholar_mcp"
    search_max_results: int = 20
    request_timeout: int = 30
    semantic_scholar_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    )


@dataclass
class ResearchNotesConfig:
    """研究笔记配置"""
    persistence_dir: str = "memory/research"
    notes_file: str = "memory/research/notes.json"
    qdrant_collection: str = "research_notes"
    vector_top_k: int = 10
    similarity_threshold: float = 0.5


@dataclass
class ResearchModeConfig:
    """研究模式 Agent 配置"""
    temperature: float = 0.3
    max_steps: int = 10
    subagent_max_steps: int = 10


@dataclass
class AcademicConfig:
    """学术 AI 伙伴总配置"""

    # --- LLM ---
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_ID", "deepseek-chat")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    )

    # --- Qdrant ---
    qdrant_url: str = field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    qdrant_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("QDRANT_API_KEY")
    )

    # --- Embedding ---
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBED_MODEL_NAME", "BAAI/bge-large-zh-v1.5"
        )
    )
    embedding_type: str = field(
        default_factory=lambda: os.getenv("EMBED_MODEL_TYPE", "local")
    )

    # 子配置
    rag: RAGConfig = field(default_factory=RAGConfig)
    learning: LearningModeConfig = field(default_factory=LearningModeConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    research: ResearchModeConfig = field(default_factory=ResearchModeConfig)
    research_notes: ResearchNotesConfig = field(default_factory=ResearchNotesConfig)


# 全局单例
_config: Optional[AcademicConfig] = None


def get_config() -> AcademicConfig:
    """获取全局配置单例"""
    global _config
    if _config is None:
        _config = AcademicConfig()
    return _config

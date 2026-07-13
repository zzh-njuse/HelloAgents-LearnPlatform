from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings owned by the product API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "HelloAgents Learn"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    database_url: str = (
        "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/hello_agents"
    )
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("./storage")

    product_embedding_provider: str = "dashscope"
    product_embedding_model: str = "text-embedding-v4"
    product_embedding_dimension: int = Field(default=1024, gt=0)
    product_embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    )
    product_embedding_api_key: str | None = None
    product_embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    product_collection_name: str = "learn_platform_source_chunks_v1"
    ingestion_queue_name: str = "learn-platform-ingestion"
    ingestion_lease_seconds: int = Field(default=120, gt=1)
    ingestion_heartbeat_seconds: int = Field(default=30, gt=0)
    ingestion_max_attempts: int = Field(default=3, ge=1)
    ingestion_reconcile_seconds: int = Field(default=30, gt=0)
    document_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    batch_max_files: int = Field(default=20, gt=0)
    batch_max_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    pdf_max_pages: int = Field(default=500, gt=0)
    parsed_text_max_chars: int = Field(default=1_000_000, gt=0)
    document_max_chunks: int = Field(default=2_000, gt=0)
    document_embedding_max_tokens: int = Field(default=1_500_000, gt=0)
    parser_timeout_seconds: int = Field(default=600, gt=0)
    workspace_max_active_ingestions: int = Field(default=3, gt=0)
    product_rag_default_top_k: int = Field(default=5, gt=0, le=20)
    product_rag_candidate_multiplier: int = Field(default=3, gt=0)
    product_rag_candidate_cap: int = Field(default=50, gt=0)
    product_rag_min_score: float | None = Field(default=0.50, ge=-1, le=1)
    product_generation_provider: str = "deepseek"
    product_generation_model: str = "deepseek-v4-flash"
    product_generation_base_url: str = "https://api.deepseek.com"
    product_generation_api_key: str | None = None
    product_generation_timeout_seconds: float = Field(default=45.0, gt=0)
    product_generation_thinking: bool = False
    product_generation_max_evidence_tokens: int = Field(default=12_000, gt=0)
    product_generation_max_output_tokens: int = Field(default=1_500, gt=0)

    request_id_header: str = "X-Request-ID"
    readiness_timeout_seconds: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_job_timing(self) -> "Settings":
        if self.ingestion_heartbeat_seconds >= self.ingestion_lease_seconds:
            raise ValueError("INGESTION_HEARTBEAT_SECONDS must be lower than INGESTION_LEASE_SECONDS")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

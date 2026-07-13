from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    display_name: str
    lifecycle_status: str
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    version_number: int
    processing_status: str
    original_filename: str
    mime_type: str
    byte_size: int
    created_at: datetime
    ready_at: datetime | None


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    document_version_id: str | None
    job_type: str
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentUploadRead(BaseModel):
    document: DocumentRead
    version: DocumentVersionRead
    job: IngestionJobRead


class DocumentSummaryRead(DocumentRead):
    current_version: DocumentVersionRead | None = None
    latest_job: IngestionJobRead | None = None


class RetrievalQuery(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class CitationRead(BaseModel):
    document_id: str
    document_version_id: str
    chunk_id: str
    document_name: str
    heading_path: list[str]
    start_offset: int
    end_offset: int


class RetrievalResult(BaseModel):
    score: float
    text: str
    citation: CitationRead


class RetrievalResponse(BaseModel):
    trace_id: str
    query: str
    results: list[RetrievalResult]


class BatchItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_ordinal: int
    display_filename: str
    declared_mime_type: str | None
    declared_byte_size: int
    status: str
    document_id: str | None
    document_version_id: str | None
    ingestion_job_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class IngestionBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    status: str
    item_count: int
    accepted_count: int
    ready_count: int
    failed_count: int
    canceled_count: int
    total_declared_bytes: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[BatchItemRead]


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=50)


class AnswerClaim(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(min_length=1, max_length=5)


class AnswerCitation(CitationRead):
    citation_id: str
    text: str


class AnswerResponse(BaseModel):
    trace_id: str
    status: str
    claims: list[AnswerClaim]
    citations: list[AnswerCitation]
    limitations: list[str] = Field(default_factory=list)
    model: str | None = None
    usage: dict[str, int | None] = Field(default_factory=dict)

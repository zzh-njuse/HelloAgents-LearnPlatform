from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug", name="uq_workspaces_slug"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceDeletionJob(Base):
    __tablename__ = "workspace_deletion_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_deletion_jobs_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # Deliberately not an FK: the minimal job remains queryable after the workspace is hard deleted.
    workspace_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_source_documents_current_version",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    parsed_storage_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parser_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_version_id", "ordinal", name="uq_document_chunks_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DocumentParseReport(Base):
    __tablename__ = "document_parse_reports"
    __table_args__ = (UniqueConstraint("document_version_id", "attempt_number", name="uq_document_parse_reports_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class RagQueryTrace(Base):
    __tablename__ = "rag_query_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    filter_summary: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_ingestion_batches_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_metadata_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="accepting", nullable=False, index=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ready_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    canceled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_declared_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionBatchItem(Base):
    __tablename__ = "ingestion_batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "client_ordinal", name="uq_ingestion_batch_items_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"), index=True, nullable=False)
    client_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    display_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    declared_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("source_documents.id"), nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    ingestion_job_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_jobs.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class RagAnswerTrace(Base):
    __tablename__ = "rag_answer_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    query_trace_id: Mapped[str | None] = mapped_column(ForeignKey("rag_query_traces.id"), nullable=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_template_version: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    current_active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_versions.id", name="fk_courses_current_active_version", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseVersion(Base):
    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "version_number", name="uq_course_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class CourseVersionSource(Base):
    __tablename__ = "course_version_sources"
    __table_args__ = (UniqueConstraint("course_version_id", "document_version_id", name="uq_course_version_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)


class CourseSection(Base):
    __tablename__ = "course_sections"
    __table_args__ = (UniqueConstraint("course_version_id", "ordinal", name="uq_course_sections_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)


class CourseSectionCitation(Base):
    __tablename__ = "course_section_citations"
    __table_args__ = (UniqueConstraint("course_section_id", "document_chunk_id", name="uq_course_section_citations_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_section_id: Mapped[str] = mapped_column(ForeignKey("course_sections.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("course_section_id", "ordinal", name="uq_lessons_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    course_section_id: Mapped[str] = mapped_column(ForeignKey("course_sections.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    current_published_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("lesson_versions.id", name="fk_lessons_current_published_version", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )


class LessonVersion(Base):
    __tablename__ = "lesson_versions"
    __table_args__ = (UniqueConstraint("lesson_id", "version_number", name="uq_lesson_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blocks: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LessonCitation(Base):
    __tablename__ = "lesson_citations"
    __table_args__ = (UniqueConstraint("lesson_version_id", "block_key", "document_chunk_id", name="uq_lesson_citations_block_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    block_key: Mapped[str] = mapped_column(String(100), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class CourseGenerationJob(Base):
    __tablename__ = "course_generation_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_course_generation_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str | None] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    output_language: Mapped[str] = mapped_column(String(10), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class CourseGenerationJobSource(Base):
    __tablename__ = "course_generation_job_sources"
    __table_args__ = (UniqueConstraint("course_generation_job_id", "document_version_id", name="uq_course_generation_job_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_generation_job_id: Mapped[str] = mapped_column(ForeignKey("course_generation_jobs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True, nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=False)


class TutorSession(Base):
    __tablename__ = "tutor_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    external_processing_ack_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_turn_ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "ordinal", "attempt_number", name="uq_tutor_turns_session_ordinal_attempt"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_tutor_turns_session_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("course_sections.id"), nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"), nullable=True)
    history_through_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_blocks: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutorTurnCitation(Base):
    __tablename__ = "tutor_turn_citations"
    __table_args__ = (UniqueConstraint("turn_id", "citation_id", name="uq_tutor_turn_citations_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    turn_id: Mapped[str] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    block_key: Mapped[str] = mapped_column(String(100), nullable=False)
    citation_id: Mapped[str] = mapped_column(String(50), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("course_generation_jobs.id"), index=True, nullable=True)
    tutor_turn_id: Mapped[str | None] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True, nullable=True)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeJob(Base):
    __tablename__ = "practice_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_practice_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    practice_set_id: Mapped[str | None] = mapped_column(ForeignKey("practice_sets.id", use_alter=True), index=True, nullable=True)
    practice_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("practice_attempts.id", use_alter=True), index=True, nullable=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), index=True, nullable=True)
    course_version_id: Mapped[str | None] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=True)
    lesson_version_id: Mapped[str | None] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=True)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    external_processing_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeJobSource(Base):
    __tablename__ = "practice_job_sources"
    __table_args__ = (UniqueConstraint("practice_job_id", "document_version_id", name="uq_practice_job_sources_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_job_id: Mapped[str] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)


class PracticeSet(Base):
    __tablename__ = "practice_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), index=True, nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True, nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id", use_alter=True), index=True, nullable=True)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeItem(Base):
    __tablename__ = "practice_items"
    __table_args__ = (UniqueConstraint("practice_set_id", "ordinal", name="uq_practice_items_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_set_id: Mapped[str] = mapped_column(ForeignKey("practice_sets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    # Hidden grading material: correct option, option rationales, rubric and
    # reference answer. Never projected into a pre-submission read schema.
    answer_spec: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeItemCitation(Base):
    __tablename__ = "practice_item_citations"
    __table_args__ = (UniqueConstraint("practice_item_id", "citation_key", name="uq_practice_item_citations_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    citation_key: Mapped[str] = mapped_column(String(50), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    document_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        UniqueConstraint("practice_item_id", "ordinal", name="uq_practice_attempts_item_ordinal"),
        UniqueConstraint("practice_item_id", "idempotency_key", name="uq_practice_attempts_item_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    answer_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="succeeded", nullable=False, index=True)
    practice_job_id: Mapped[str | None] = mapped_column(ForeignKey("practice_jobs.id"), index=True, nullable=True)
    external_processing_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PracticeFeedback(Base):
    __tablename__ = "practice_feedback"
    __table_args__ = (UniqueConstraint("practice_attempt_id", name="uq_practice_feedback_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_attempt_id: Mapped[str] = mapped_column(ForeignKey("practice_attempts.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    verdict: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criterion_results: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    feedback_blocks: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    is_ai_graded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# --------------------------------------------------------------------------- #
# Stage 4 Slice 2: Mastery, Review and Memory
# --------------------------------------------------------------------------- #


class LearningTarget(Base):
    __tablename__ = "learning_targets"
    __table_args__ = (UniqueConstraint("lesson_version_id", "target_key", name="uq_learning_targets_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    target_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # objective | lesson_overall
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PracticeItemTarget(Base):
    __tablename__ = "practice_item_targets"
    __table_args__ = (UniqueConstraint("practice_item_id", "learning_target_id", "criterion_key", name="uq_practice_item_targets_item_target_criterion"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    criterion_key: Mapped[str | None] = mapped_column(String(100), nullable=True)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (UniqueConstraint("practice_feedback_id", name="uq_learning_events_feedback"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # practice_result
    practice_attempt_id: Mapped[str] = mapped_column(ForeignKey("practice_attempts.id"), index=True, nullable=False)
    practice_feedback_id: Mapped[str] = mapped_column(ForeignKey("practice_feedback.id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MasterySignal(Base):
    __tablename__ = "mastery_signals"
    __table_args__ = (UniqueConstraint("learning_event_id", "learning_target_id", name="uq_mastery_signals_event_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), nullable=False)
    practice_set_id: Mapped[str] = mapped_column(ForeignKey("practice_sets.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # positive | partial | negative
    value: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)  # single_choice | short_answer
    is_ai_derived: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MasteryState(Base):
    __tablename__ = "mastery_states"
    __table_args__ = (UniqueConstraint("learning_target_id", name="uq_mastery_states_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    band: Mapped[str] = mapped_column(String(20), nullable=False)  # insufficient | needs_review | developing | secure
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_set_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    projection_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), default="001", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Weakness(Base):
    __tablename__ = "weaknesses"
    __table_args__ = (UniqueConstraint("learning_target_id", name="uq_weaknesses_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="provisional", nullable=False)  # provisional|confirmed|resolved|dismissed
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_negative_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    last_negative_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    memory_suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("weakness_id", name="uq_review_items_weakness"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    weakness_id: Mapped[str] = mapped_column(ForeignKey("weaknesses.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="due", nullable=False)  # due|reviewing|awaiting_validation|snoozed|dismissed|resolved
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_item_id: Mapped[str] = mapped_column(ForeignKey("review_items.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # reviewing|reviewed|snooze|dismiss|reopen
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LearningProjectionJob(Base):
    __tablename__ = "learning_projection_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_learning_projection_jobs_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LearningMemory(Base):
    __tablename__ = "learning_memories"
    __table_args__ = (
        Index(
            "uq_learning_memories_current_target",
            "learning_target_id",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
            sqlite_where=text("status <> 'archived'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id"), index=True, nullable=False)
    learning_target_id: Mapped[str] = mapped_column(ForeignKey("learning_targets.id"), index=True, nullable=False)
    weakness_id: Mapped[str | None] = mapped_column(ForeignKey("weaknesses.id", use_alter=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # weakness
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|needs_review|paused|archived
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class LearningMemorySource(Base):
    __tablename__ = "learning_memory_sources"
    __table_args__ = (UniqueConstraint("learning_memory_id", "learning_event_id", name="uq_learning_memory_sources_memory_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_memory_id: Mapped[str] = mapped_column(ForeignKey("learning_memories.id", ondelete="CASCADE"), index=True, nullable=False)
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)


class LearningMemoryRevision(Base):
    __tablename__ = "learning_memory_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    learning_memory_id: Mapped[str] = mapped_column(ForeignKey("learning_memories.id", ondelete="CASCADE"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # auto_created|edited|reconfirmed|paused|archived|conflicted
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LearningMemoryPolicy(Base):
    __tablename__ = "learning_memory_policies"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_learning_memory_policies_workspace"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=False)
    tutor_use_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class LessonCompletion(Base):
    __tablename__ = "lesson_completions"
    __table_args__ = (UniqueConstraint("workspace_id", "lesson_version_id", name="uq_lesson_completions_workspace_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    course_version_id: Mapped[str] = mapped_column(ForeignKey("course_versions.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_version_id: Mapped[str] = mapped_column(ForeignKey("lesson_versions.id", ondelete="CASCADE"), index=True, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

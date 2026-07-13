"""create document lifecycle tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_source_documents_workspace_id", "source_documents", ["workspace_id"])
    op.create_index("ix_source_documents_lifecycle_status", "source_documents", ["lifecycle_status"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_storage_uri", sa.String(length=500), nullable=False),
        sa.Column("parsed_storage_uri", sa.String(length=500), nullable=True),
        sa.Column("parser_key", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_processing_status", "document_versions", ["processing_status"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency_key"),
    )
    op.create_index("ix_ingestion_jobs_workspace_id", "ingestion_jobs", ["workspace_id"])
    op.create_index("ix_ingestion_jobs_document_version_id", "ingestion_jobs", ["document_version_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_version_id", "ordinal", name="uq_document_chunks_ordinal"),
    )
    op.create_index("ix_document_chunks_document_version_id", "document_chunks", ["document_version_id"])

    op.create_table(
        "document_parse_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("parser_key", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=True),
        sa.Column("character_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_version_id", "attempt_number", name="uq_document_parse_reports_attempt"),
    )
    op.create_index("ix_document_parse_reports_document_version_id", "document_parse_reports", ["document_version_id"])


def downgrade() -> None:
    op.drop_table("document_parse_reports")
    op.drop_table("document_chunks")
    op.drop_table("ingestion_jobs")
    op.drop_table("document_versions")
    op.drop_table("source_documents")

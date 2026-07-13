"""add slice 2 batches and answer traces

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_metadata_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("ready_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("canceled_count", sa.Integer(), nullable=False),
        sa.Column("total_declared_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_ingestion_batches_workspace_key"),
    )
    op.create_index("ix_ingestion_batches_workspace_id", "ingestion_batches", ["workspace_id"])
    op.create_index("ix_ingestion_batches_status", "ingestion_batches", ["status"])
    op.create_table(
        "ingestion_batch_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), sa.ForeignKey("ingestion_batches.id"), nullable=False),
        sa.Column("client_ordinal", sa.Integer(), nullable=False),
        sa.Column("display_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_mime_type", sa.String(length=100), nullable=True),
        sa.Column("declared_byte_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=True),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=True),
        sa.Column("ingestion_job_id", sa.String(length=36), sa.ForeignKey("ingestion_jobs.id"), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "client_ordinal", name="uq_ingestion_batch_items_ordinal"),
    )
    op.create_index("ix_ingestion_batch_items_batch_id", "ingestion_batch_items", ["batch_id"])
    op.create_index("ix_ingestion_batch_items_status", "ingestion_batch_items", ["status"])
    op.create_table(
        "rag_answer_traces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("query_trace_id", sa.String(length=36), sa.ForeignKey("rag_query_traces.id"), nullable=True),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=50), nullable=False),
        sa.Column("evidence_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("retrieval_latency_ms", sa.Integer(), nullable=True),
        sa.Column("generation_latency_ms", sa.Integer(), nullable=True),
        sa.Column("answer_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rag_answer_traces_workspace_id", "rag_answer_traces", ["workspace_id"])
    op.create_index("ix_rag_answer_traces_status", "rag_answer_traces", ["status"])


def downgrade() -> None:
    op.drop_index("ix_rag_answer_traces_status", table_name="rag_answer_traces")
    op.drop_index("ix_rag_answer_traces_workspace_id", table_name="rag_answer_traces")
    op.drop_table("rag_answer_traces")
    op.drop_index("ix_ingestion_batch_items_status", table_name="ingestion_batch_items")
    op.drop_index("ix_ingestion_batch_items_batch_id", table_name="ingestion_batch_items")
    op.drop_table("ingestion_batch_items")
    op.drop_index("ix_ingestion_batches_status", table_name="ingestion_batches")
    op.drop_index("ix_ingestion_batches_workspace_id", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")

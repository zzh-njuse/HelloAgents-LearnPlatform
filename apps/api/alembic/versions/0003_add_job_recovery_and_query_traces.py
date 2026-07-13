"""add job recovery fields and query traces

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("worker_id", sa.String(length=100), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_ingestion_jobs_lease_expires_at", "ingestion_jobs", ["lease_expires_at"])
    op.create_index("ix_ingestion_jobs_next_attempt_at", "ingestion_jobs", ["next_attempt_at"])
    op.create_table(
        "rag_query_traces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(length=200), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rag_query_traces_workspace_id", "rag_query_traces", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("rag_query_traces")
    op.drop_index("ix_ingestion_jobs_next_attempt_at", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_lease_expires_at", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "next_attempt_at")
    op.drop_column("ingestion_jobs", "heartbeat_at")
    op.drop_column("ingestion_jobs", "lease_expires_at")
    op.drop_column("ingestion_jobs", "worker_id")

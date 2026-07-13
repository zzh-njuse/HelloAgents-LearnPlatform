"""add query filter summary

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_query_traces", sa.Column("filter_summary", sa.JSON(), nullable=True))
    op.execute("UPDATE rag_query_traces SET filter_summary = '{}' WHERE filter_summary IS NULL")
    op.alter_column("rag_query_traces", "filter_summary", nullable=False)


def downgrade() -> None:
    op.drop_column("rag_query_traces", "filter_summary")

"""add parse report metadata

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_parse_reports", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("document_parse_reports", sa.Column("warning_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_parse_reports", "warning_codes")
    op.drop_column("document_parse_reports", "page_count")

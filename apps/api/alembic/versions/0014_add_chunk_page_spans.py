"""add optional page spans to document chunks

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("page_start", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("page_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "page_end")
    op.drop_column("document_chunks", "page_start")

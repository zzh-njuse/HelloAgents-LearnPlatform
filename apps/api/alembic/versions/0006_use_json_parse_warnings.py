"""store parse warnings as JSON

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "document_parse_reports",
        "warning_codes",
        existing_type=sa.Text(),
        type_=sa.JSON(),
        postgresql_using="warning_codes::json",
    )


def downgrade() -> None:
    op.alter_column(
        "document_parse_reports",
        "warning_codes",
        existing_type=sa.JSON(),
        type_=sa.Text(),
        postgresql_using="warning_codes::text",
    )

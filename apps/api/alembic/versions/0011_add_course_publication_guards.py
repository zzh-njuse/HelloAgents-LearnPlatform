"""add course publication uniqueness guards

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_course_versions_one_active", "course_versions", ["course_id"], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_index("uq_lesson_versions_one_published", "lesson_versions", ["lesson_id"], unique=True, postgresql_where=sa.text("status = 'published'"))


def downgrade() -> None:
    op.drop_index("uq_lesson_versions_one_published", table_name="lesson_versions")
    op.drop_index("uq_course_versions_one_active", table_name="course_versions")

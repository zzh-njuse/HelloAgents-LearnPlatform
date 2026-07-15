"""add output language to course generation jobs

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("course_generation_jobs", sa.Column("output_language", sa.String(length=10), nullable=False, server_default="zh-CN"))
    op.create_check_constraint("ck_course_generation_jobs_output_language", "course_generation_jobs", "output_language IN ('zh-CN', 'en')")
    op.alter_column("course_generation_jobs", "output_language", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_course_generation_jobs_output_language", "course_generation_jobs", type_="check")
    op.drop_column("course_generation_jobs", "output_language")

"""add lesson completion facts

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_completions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "lesson_version_id", name="uq_lesson_completions_workspace_version"),
    )
    for column in ("workspace_id", "course_id", "course_version_id", "lesson_id", "lesson_version_id"):
        op.create_index(f"ix_lesson_completions_{column}", "lesson_completions", [column])


def downgrade() -> None:
    op.drop_table("lesson_completions")

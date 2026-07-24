"""add practice_jobs.artifact_contract_version (Slice 5, ADR 007 §3.9)

Revision ID: 0023
Revises: 0022

Single additive migration: a non-null ``artifact_contract_version`` column on
``practice_jobs``. Existing rows backfill to ``practice_artifact_v1``; new Jobs
pin the approved version at creation. No other column, table or Job state is
added. Downgrade only drops this column (it never touches Set/Item/Attempt/
Feedback history).
"""

from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first so the column exists on all backends, then backfill,
    # then enforce non-null. A server default keeps new application-inserted
    # rows safe, but the ORM writes the version explicitly for new Jobs.
    op.add_column(
        "practice_jobs",
        sa.Column(
            "artifact_contract_version",
            sa.String(length=40),
            nullable=True,
            server_default="practice_artifact_v1",
        ),
    )
    op.execute(
        "UPDATE practice_jobs SET artifact_contract_version = 'practice_artifact_v1' "
        "WHERE artifact_contract_version IS NULL"
    )
    op.alter_column("practice_jobs", "artifact_contract_version", nullable=False)


def downgrade() -> None:
    # Additive only: dropping the column never changes Set/Item/Attempt/Feedback.
    op.drop_column("practice_jobs", "artifact_contract_version")

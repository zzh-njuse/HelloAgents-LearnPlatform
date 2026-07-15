"""add workspace deletion lifecycle

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("lifecycle_status", sa.String(length=20), nullable=False, server_default="active"))
    op.add_column("workspaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_workspaces_lifecycle_status", "workspaces", ["lifecycle_status"])
    op.create_table(
        "workspace_deletion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_deletion_jobs_key"),
    )
    op.create_index("ix_workspace_deletion_jobs_workspace_id", "workspace_deletion_jobs", ["workspace_id"])
    op.create_index("ix_workspace_deletion_jobs_status", "workspace_deletion_jobs", ["status"])
    op.create_index("ix_workspace_deletion_jobs_lease_expires_at", "workspace_deletion_jobs", ["lease_expires_at"])
    op.create_index("ix_workspace_deletion_jobs_next_attempt_at", "workspace_deletion_jobs", ["next_attempt_at"])
    op.alter_column("workspaces", "lifecycle_status", server_default=None)


def downgrade() -> None:
    op.drop_table("workspace_deletion_jobs")
    op.drop_index("ix_workspaces_lifecycle_status", table_name="workspaces")
    op.drop_column("workspaces", "deleted_at")
    op.drop_column("workspaces", "lifecycle_status")

"""add bounded tutor sessions and turns

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tutor_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("external_processing_ack_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_turn_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    for column in ("workspace_id", "course_id", "course_version_id", "status"):
        op.create_index(f"ix_tutor_sessions_{column}", "tutor_sessions", [column])
    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("tutor_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("section_id", sa.String(36), sa.ForeignKey("course_sections.id")),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id")),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id")),
        sa.Column("history_through_ordinal", sa.Integer(), nullable=False),
        sa.Column("answer_blocks", sa.JSON()),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "ordinal", "attempt_number", name="uq_tutor_turns_session_ordinal_attempt"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_tutor_turns_session_key"),
    )
    for column in ("session_id", "workspace_id", "status", "lease_expires_at", "next_attempt_at"):
        op.create_index(f"ix_tutor_turns_{column}", "tutor_turns", [column])
    op.create_index("uq_tutor_turns_one_active", "tutor_turns", ["session_id"], unique=True, postgresql_where=sa.text("status IN ('queued','running','retry_wait','cancel_requested')"))
    op.create_table(
        "tutor_turn_citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("block_key", sa.String(100), nullable=False),
        sa.Column("citation_id", sa.String(50), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("document_chunk_id", sa.String(36), sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.UniqueConstraint("turn_id", "citation_id", name="uq_tutor_turn_citations_id"),
    )
    op.create_index("ix_tutor_turn_citations_turn_id", "tutor_turn_citations", ["turn_id"])
    op.create_index("ix_tutor_turn_citations_workspace_id", "tutor_turn_citations", ["workspace_id"])
    op.alter_column("agent_runs", "course_generation_job_id", existing_type=sa.String(36), nullable=True)
    op.add_column("agent_runs", sa.Column("tutor_turn_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_agent_runs_tutor_turn", "agent_runs", "tutor_turns", ["tutor_turn_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_agent_runs_tutor_turn_id", "agent_runs", ["tutor_turn_id"])
    op.create_check_constraint("ck_agent_runs_one_owner", "agent_runs", "(course_generation_job_id IS NULL) <> (tutor_turn_id IS NULL)")


def downgrade() -> None:
    # Tutor-owned traces cannot exist once tutor_turn_id is removed. Remove them
    # before restoring the legacy non-null course job owner constraint.
    op.execute(
        sa.text(
            "DELETE FROM agent_tool_calls WHERE agent_run_id IN "
            "(SELECT id FROM agent_runs WHERE tutor_turn_id IS NOT NULL)"
        )
    )
    op.execute(sa.text("DELETE FROM agent_runs WHERE tutor_turn_id IS NOT NULL"))
    op.drop_constraint("ck_agent_runs_one_owner", "agent_runs", type_="check")
    op.drop_index("ix_agent_runs_tutor_turn_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_tutor_turn", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "tutor_turn_id")
    op.alter_column("agent_runs", "course_generation_job_id", existing_type=sa.String(36), nullable=False)
    op.drop_table("tutor_turn_citations")
    op.drop_index("uq_tutor_turns_one_active", table_name="tutor_turns")
    op.drop_table("tutor_turns")
    op.drop_table("tutor_sessions")

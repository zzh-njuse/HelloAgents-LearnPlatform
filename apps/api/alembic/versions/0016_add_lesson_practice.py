"""add lesson practice sets, items, attempts, feedback and jobs

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # practice_jobs is created first without its cyclic FKs to practice_sets /
    # practice_attempts; those are added once the referenced tables exist.
    op.create_table(
        "practice_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column("practice_set_id", sa.String(36), nullable=True),
        sa.Column("practice_attempt_id", sa.String(36), nullable=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=True),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id"), nullable=True),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id"), nullable=True),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id"), nullable=True),
        sa.Column("output_language", sa.String(10), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("external_processing_ack_at", sa.DateTime(timezone=True)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_practice_jobs_workspace_key"),
    )
    op.create_check_constraint("ck_practice_jobs_job_type", "practice_jobs", "job_type IN ('generate_set', 'grade_attempt')")
    op.create_check_constraint("ck_practice_jobs_output_language", "practice_jobs", "output_language IN ('zh-CN', 'en')")
    for column in ("workspace_id", "job_type", "practice_set_id", "practice_attempt_id", "status", "lease_expires_at", "next_attempt_at"):
        op.create_index(f"ix_practice_jobs_{column}", "practice_jobs", [column])

    op.create_table(
        "practice_job_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("practice_job_id", sa.String(36), sa.ForeignKey("practice_jobs.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.UniqueConstraint("practice_job_id", "document_version_id", name="uq_practice_job_sources_version"),
    )
    op.create_index("ix_practice_job_sources_practice_job_id", "practice_job_sources", ["practice_job_id"])
    op.create_index("ix_practice_job_sources_workspace_id", "practice_job_sources", ["workspace_id"])

    op.create_table(
        "practice_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("practice_job_id", sa.String(36), nullable=True),
        sa.Column("output_language", sa.String(10), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("generation_config", sa.JSON(), nullable=False),
        sa.Column("lifecycle_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint("ck_practice_sets_lifecycle_status", "practice_sets", "lifecycle_status IN ('active', 'deleting')")
    op.create_check_constraint("ck_practice_sets_output_language", "practice_sets", "output_language IN ('zh-CN', 'en')")
    for column in ("workspace_id", "course_id", "course_version_id", "lesson_id", "lesson_version_id", "practice_job_id", "lifecycle_status"):
        op.create_index(f"ix_practice_sets_{column}", "practice_sets", [column])

    op.create_table(
        "practice_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("practice_set_id", sa.String(36), sa.ForeignKey("practice_sets.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON()),
        sa.Column("answer_spec", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("practice_set_id", "ordinal", name="uq_practice_items_ordinal"),
    )
    op.create_check_constraint("ck_practice_items_item_type", "practice_items", "item_type IN ('single_choice', 'short_answer')")
    op.create_index("ix_practice_items_practice_set_id", "practice_items", ["practice_set_id"])
    op.create_index("ix_practice_items_workspace_id", "practice_items", ["workspace_id"])

    op.create_table(
        "practice_item_citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("practice_item_id", sa.String(36), sa.ForeignKey("practice_items.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("citation_key", sa.String(50), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("document_chunk_id", sa.String(36), sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.UniqueConstraint("practice_item_id", "citation_key", name="uq_practice_item_citations_key"),
    )
    op.create_index("ix_practice_item_citations_practice_item_id", "practice_item_citations", ["practice_item_id"])
    op.create_index("ix_practice_item_citations_workspace_id", "practice_item_citations", ["workspace_id"])

    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("practice_item_id", sa.String(36), sa.ForeignKey("practice_items.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("answer_payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("practice_job_id", sa.String(36), sa.ForeignKey("practice_jobs.id")),
        sa.Column("external_processing_ack_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("practice_item_id", "ordinal", name="uq_practice_attempts_item_ordinal"),
        sa.UniqueConstraint("practice_item_id", "idempotency_key", name="uq_practice_attempts_item_key"),
    )
    for column in ("workspace_id", "practice_item_id", "status", "practice_job_id", "lease_expires_at", "next_attempt_at"):
        op.create_index(f"ix_practice_attempts_{column}", "practice_attempts", [column])

    op.create_table(
        "practice_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("practice_attempt_id", sa.String(36), sa.ForeignKey("practice_attempts.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("criterion_results", sa.JSON()),
        sa.Column("feedback_blocks", sa.JSON(), nullable=False),
        sa.Column("is_ai_graded", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("practice_attempt_id", name="uq_practice_feedback_attempt"),
    )
    op.create_check_constraint("ck_practice_feedback_verdict", "practice_feedback", "verdict IN ('correct', 'partially_correct', 'incorrect', 'ungradable')")
    op.create_index("ix_practice_feedback_practice_attempt_id", "practice_feedback", ["practice_attempt_id"])
    op.create_index("ix_practice_feedback_workspace_id", "practice_feedback", ["workspace_id"])

    # Cyclic FKs deferred until both sides exist.
    op.create_foreign_key("fk_practice_jobs_practice_set", "practice_jobs", "practice_sets", ["practice_set_id"], ["id"])
    op.create_foreign_key("fk_practice_jobs_practice_attempt", "practice_jobs", "practice_attempts", ["practice_attempt_id"], ["id"])
    op.create_foreign_key("fk_practice_sets_practice_job", "practice_sets", "practice_jobs", ["practice_job_id"], ["id"])

    # AgentRun gains an optional Practice Job owner. Replace the two-way XOR
    # constraint with an exactly-one-of-three owner check.
    op.add_column("agent_runs", sa.Column("practice_job_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_agent_runs_practice_job", "agent_runs", "practice_jobs", ["practice_job_id"], ["id"])
    op.create_index("ix_agent_runs_practice_job_id", "agent_runs", ["practice_job_id"])
    op.drop_constraint("ck_agent_runs_one_owner", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_one_owner",
        "agent_runs",
        "((course_generation_job_id IS NOT NULL)::int + (tutor_turn_id IS NOT NULL)::int + (practice_job_id IS NOT NULL)::int) = 1",
    )


def downgrade() -> None:
    # Remove practice-owned traces before restoring the two-owner constraint.
    op.execute(
        sa.text(
            "DELETE FROM agent_tool_calls WHERE agent_run_id IN "
            "(SELECT id FROM agent_runs WHERE practice_job_id IS NOT NULL)"
        )
    )
    op.execute(sa.text("DELETE FROM agent_runs WHERE practice_job_id IS NOT NULL"))
    op.drop_constraint("ck_agent_runs_one_owner", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_one_owner", "agent_runs", "(course_generation_job_id IS NULL) <> (tutor_turn_id IS NULL)")
    op.drop_index("ix_agent_runs_practice_job_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_practice_job", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "practice_job_id")

    op.drop_constraint("fk_practice_sets_practice_job", "practice_sets", type_="foreignkey")
    op.drop_constraint("fk_practice_jobs_practice_attempt", "practice_jobs", type_="foreignkey")
    op.drop_constraint("fk_practice_jobs_practice_set", "practice_jobs", type_="foreignkey")

    op.drop_table("practice_feedback")
    op.drop_table("practice_attempts")
    op.drop_table("practice_item_citations")
    op.drop_table("practice_items")
    op.drop_table("practice_sets")
    op.drop_table("practice_job_sources")
    op.drop_index("ix_practice_jobs_practice_attempt_id", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_practice_set_id", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_next_attempt_at", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_lease_expires_at", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_status", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_job_type", table_name="practice_jobs")
    op.drop_index("ix_practice_jobs_workspace_id", table_name="practice_jobs")
    op.drop_table("practice_jobs")

"""add versioned courses and controlled generation facts

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False),
        sa.Column("current_active_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("lifecycle_status IN ('active', 'deleted')", name="ck_courses_lifecycle_status"),
    )
    op.create_index("ix_courses_workspace_id", "courses", ["workspace_id"])
    op.create_index("ix_courses_lifecycle_status", "courses", ["lifecycle_status"])
    op.create_table(
        "course_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_id", sa.String(length=36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "version_number", name="uq_course_versions_number"),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_course_versions_status"),
    )
    op.create_index("ix_course_versions_course_id", "course_versions", ["course_id"])
    op.create_index("ix_course_versions_workspace_id", "course_versions", ["workspace_id"])
    op.create_index("ix_course_versions_status", "course_versions", ["status"])
    op.create_foreign_key("fk_courses_current_active_version", "courses", "course_versions", ["current_active_version_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "course_version_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_version_id", sa.String(length=36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.UniqueConstraint("course_version_id", "document_version_id", name="uq_course_version_sources_version"),
    )
    op.create_index("ix_course_version_sources_course_version_id", "course_version_sources", ["course_version_id"])
    op.create_index("ix_course_version_sources_workspace_id", "course_version_sources", ["workspace_id"])
    op.create_index("ix_course_version_sources_document_id", "course_version_sources", ["document_id"])
    op.create_index("ix_course_version_sources_document_version_id", "course_version_sources", ["document_version_id"])
    op.create_table(
        "course_sections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_version_id", sa.String(length=36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.UniqueConstraint("course_version_id", "ordinal", name="uq_course_sections_ordinal"),
    )
    op.create_index("ix_course_sections_course_version_id", "course_sections", ["course_version_id"])
    op.create_index("ix_course_sections_workspace_id", "course_sections", ["workspace_id"])
    op.create_table(
        "course_section_citations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_section_id", sa.String(length=36), sa.ForeignKey("course_sections.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("document_chunk_id", sa.String(length=36), sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.UniqueConstraint("course_section_id", "document_chunk_id", name="uq_course_section_citations_chunk"),
    )
    op.create_index("ix_course_section_citations_course_section_id", "course_section_citations", ["course_section_id"])
    op.create_index("ix_course_section_citations_workspace_id", "course_section_citations", ["workspace_id"])
    op.create_table(
        "lessons",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_version_id", sa.String(length=36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("course_section_id", sa.String(length=36), sa.ForeignKey("course_sections.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("current_published_version_id", sa.String(length=36), nullable=True),
        sa.UniqueConstraint("course_section_id", "ordinal", name="uq_lessons_ordinal"),
    )
    op.create_index("ix_lessons_course_version_id", "lessons", ["course_version_id"])
    op.create_index("ix_lessons_course_section_id", "lessons", ["course_section_id"])
    op.create_index("ix_lessons_workspace_id", "lessons", ["workspace_id"])
    op.create_table(
        "lesson_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lesson_id", sa.String(length=36), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("course_version_id", sa.String(length=36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("learning_objectives", sa.JSON(), nullable=False),
        sa.Column("blocks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("lesson_id", "version_number", name="uq_lesson_versions_number"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded')", name="ck_lesson_versions_status"),
    )
    op.create_index("ix_lesson_versions_lesson_id", "lesson_versions", ["lesson_id"])
    op.create_index("ix_lesson_versions_course_version_id", "lesson_versions", ["course_version_id"])
    op.create_index("ix_lesson_versions_workspace_id", "lesson_versions", ["workspace_id"])
    op.create_index("ix_lesson_versions_status", "lesson_versions", ["status"])
    op.create_table(
        "lesson_citations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lesson_version_id", sa.String(length=36), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("block_key", sa.String(length=100), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("document_chunk_id", sa.String(length=36), sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.UniqueConstraint("lesson_version_id", "block_key", "document_chunk_id", name="uq_lesson_citations_block_chunk"),
    )
    op.create_index("ix_lesson_citations_lesson_version_id", "lesson_citations", ["lesson_version_id"])
    op.create_index("ix_lesson_citations_workspace_id", "lesson_citations", ["workspace_id"])
    op.create_foreign_key("fk_lessons_current_published_version", "lessons", "lesson_versions", ["current_published_version_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "course_generation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("course_id", sa.String(length=36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("course_version_id", sa.String(length=36), sa.ForeignKey("course_versions.id"), nullable=True),
        sa.Column("lesson_id", sa.String(length=36), sa.ForeignKey("lessons.id"), nullable=True),
        sa.Column("job_type", sa.String(length=30), nullable=False),
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
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_course_generation_jobs_workspace_key"),
        sa.CheckConstraint("job_type IN ('course_outline', 'lesson_draft')", name="ck_course_generation_jobs_type"),
        sa.CheckConstraint("status IN ('queued', 'running', 'retry_wait', 'failed', 'succeeded', 'cancel_requested', 'canceled', 'queue_failed')", name="ck_course_generation_jobs_status"),
    )
    for name, columns in (("ix_course_generation_jobs_workspace_id", ["workspace_id"]), ("ix_course_generation_jobs_course_id", ["course_id"]), ("ix_course_generation_jobs_course_version_id", ["course_version_id"]), ("ix_course_generation_jobs_lesson_id", ["lesson_id"]), ("ix_course_generation_jobs_status", ["status"]), ("ix_course_generation_jobs_lease_expires_at", ["lease_expires_at"]), ("ix_course_generation_jobs_next_attempt_at", ["next_attempt_at"])):
        op.create_index(name, "course_generation_jobs", columns)
    op.create_table(
        "course_generation_job_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_generation_job_id", sa.String(length=36), sa.ForeignKey("course_generation_jobs.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.UniqueConstraint("course_generation_job_id", "document_version_id", name="uq_course_generation_job_sources_version"),
    )
    for name, columns in (("ix_course_generation_job_sources_course_generation_job_id", ["course_generation_job_id"]), ("ix_course_generation_job_sources_workspace_id", ["workspace_id"]), ("ix_course_generation_job_sources_document_id", ["document_id"]), ("ix_course_generation_job_sources_document_version_id", ["document_version_id"])):
        op.create_index(name, "course_generation_job_sources", columns)
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_generation_job_id", sa.String(length=36), sa.ForeignKey("course_generation_jobs.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_course_generation_job_id", "agent_runs", ["course_generation_job_id"])
    op.create_index("ix_agent_runs_workspace_id", "agent_runs", ["workspace_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_run_id", sa.String(length=36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_run_id", "ordinal", name="uq_agent_tool_calls_ordinal"),
    )
    op.create_index("ix_agent_tool_calls_agent_run_id", "agent_tool_calls", ["agent_run_id"])
    op.create_index("ix_agent_tool_calls_workspace_id", "agent_tool_calls", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_lesson_citations_workspace_id", table_name="lesson_citations")
    op.drop_index("ix_lesson_citations_lesson_version_id", table_name="lesson_citations")
    op.drop_table("lesson_citations")
    op.drop_index("ix_agent_tool_calls_workspace_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_agent_run_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_workspace_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_course_generation_job_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    for name in ("ix_course_generation_job_sources_document_version_id", "ix_course_generation_job_sources_document_id", "ix_course_generation_job_sources_workspace_id", "ix_course_generation_job_sources_course_generation_job_id"):
        op.drop_index(name, table_name="course_generation_job_sources")
    op.drop_table("course_generation_job_sources")
    for name in ("ix_course_generation_jobs_next_attempt_at", "ix_course_generation_jobs_lease_expires_at", "ix_course_generation_jobs_status", "ix_course_generation_jobs_lesson_id", "ix_course_generation_jobs_course_version_id", "ix_course_generation_jobs_course_id", "ix_course_generation_jobs_workspace_id"):
        op.drop_index(name, table_name="course_generation_jobs")
    op.drop_table("course_generation_jobs")
    op.drop_constraint("fk_lessons_current_published_version", "lessons", type_="foreignkey")
    for name in ("ix_lesson_versions_status", "ix_lesson_versions_workspace_id", "ix_lesson_versions_course_version_id", "ix_lesson_versions_lesson_id"):
        op.drop_index(name, table_name="lesson_versions")
    op.drop_table("lesson_versions")
    for name in ("ix_lessons_workspace_id", "ix_lessons_course_section_id", "ix_lessons_course_version_id"):
        op.drop_index(name, table_name="lessons")
    op.drop_table("lessons")
    op.drop_index("ix_course_section_citations_workspace_id", table_name="course_section_citations")
    op.drop_index("ix_course_section_citations_course_section_id", table_name="course_section_citations")
    op.drop_table("course_section_citations")
    for name in ("ix_course_sections_workspace_id", "ix_course_sections_course_version_id"):
        op.drop_index(name, table_name="course_sections")
    op.drop_table("course_sections")
    for name in ("ix_course_version_sources_document_version_id", "ix_course_version_sources_document_id", "ix_course_version_sources_workspace_id", "ix_course_version_sources_course_version_id"):
        op.drop_index(name, table_name="course_version_sources")
    op.drop_table("course_version_sources")
    op.drop_constraint("fk_courses_current_active_version", "courses", type_="foreignkey")
    for name in ("ix_course_versions_status", "ix_course_versions_workspace_id", "ix_course_versions_course_id"):
        op.drop_index(name, table_name="course_versions")
    op.drop_table("course_versions")
    op.drop_index("ix_courses_lifecycle_status", table_name="courses")
    op.drop_index("ix_courses_workspace_id", table_name="courses")
    op.drop_table("courses")

"""0021_add_integrated_learning_tools

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-21

Per SLICE_4_GLM_IMPLEMENTATION_PACKET_002 §7:
- job_tool_authorizations: per-Job MCP tool authorization with owner check
- PracticeJob: item_type_mode, code_languages
- PracticeItem: interaction_spec (nullable JSON for coding items)
- PracticeAttempt: source_code column
- PracticeFeedback: coding execution summary fields
- TutorTurn: code_tool_authorized, code_tool_used, code_tool_call_count
- LessonGenerationJob: science_tool_authorized
"""

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. job_tool_authorizations — per-Job MCP tool authorization
    # ------------------------------------------------------------------
    op.create_table(
        "job_tool_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("capability_id", sa.String(50), nullable=False),
        # Owner: exactly one of these must be non-null (enforced by check constraint)
        sa.Column("course_generation_job_id", sa.String(36), sa.ForeignKey("course_generation_jobs.id"), nullable=True, index=True),
        sa.Column("practice_job_id", sa.String(36), sa.ForeignKey("practice_jobs.id"), nullable=True, index=True),
        # Budget
        sa.Column("max_calls", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("used_calls", sa.Integer(), nullable=False, server_default="0"),
        # MCP snapshot
        sa.Column("server_allowlist", sa.Text(), nullable=True),  # JSON array of allowed tools
        sa.Column("schema_hash_snapshot", sa.String(64), nullable=True),
        sa.Column("protocol_version_snapshot", sa.String(20), nullable=True),
        # Timestamps
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        # Check constraint: exactly one owner non-null
        sa.CheckConstraint(
            "((CASE WHEN course_generation_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN practice_job_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
            name="ck_job_tool_auth_one_owner",
        ),
    )
    # Partial unique indexes for owner+capability uniqueness
    # (Postgres partial indexes; SQLite ignores the WHERE clause)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_tool_auth_course_cap "
        "ON job_tool_authorizations (course_generation_job_id, capability_id) "
        "WHERE course_generation_job_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_tool_auth_practice_cap "
        "ON job_tool_authorizations (practice_job_id, capability_id) "
        "WHERE practice_job_id IS NOT NULL"
    )

    # ------------------------------------------------------------------
    # 2. PracticeJob extensions
    # ------------------------------------------------------------------
    op.add_column(
        "practice_jobs",
        sa.Column("item_type_mode", sa.String(20), nullable=False, server_default="auto"),
    )
    op.add_column(
        "practice_jobs",
        sa.Column("code_languages", sa.JSON(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. PracticeItem extensions
    # ------------------------------------------------------------------
    op.add_column(
        "practice_items",
        sa.Column("interaction_spec", sa.JSON(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 4. PracticeAttempt extensions
    # ------------------------------------------------------------------
    op.add_column(
        "practice_attempts",
        sa.Column("source_code", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5. PracticeFeedback extensions (coding execution summary)
    # ------------------------------------------------------------------
    op.add_column(
        "practice_feedback",
        sa.Column("coding_tests_passed", sa.Integer(), nullable=True),
    )
    op.add_column(
        "practice_feedback",
        sa.Column("coding_tests_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "practice_feedback",
        sa.Column("coding_error_categories", sa.JSON(), nullable=True),
    )
    op.add_column(
        "practice_feedback",
        sa.Column("coding_public_cases", sa.JSON(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 6. TutorTurn extensions
    # ------------------------------------------------------------------
    op.add_column(
        "tutor_turns",
        sa.Column("code_tool_authorized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tutor_turns",
        sa.Column("code_tool_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tutor_turns",
        sa.Column("code_tool_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tutor_turns",
        sa.Column("science_tool_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tutor_turns",
        sa.Column("science_tool_call_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # ------------------------------------------------------------------
    # 7. CourseGenerationJob extensions (Lesson Writer science auth)
    # ------------------------------------------------------------------
    op.add_column(
        "course_generation_jobs",
        sa.Column("science_tool_authorized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # ------------------------------------------------------------------
    # 8. LessonVersion extensions (practice_type_hints for structural
    #    type adaptation — per Correction 011 §1.2)
    # ------------------------------------------------------------------
    op.add_column(
        "lesson_versions",
        sa.Column("practice_type_hints", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    # Reverse order of upgrade
    # 7
    op.drop_column("course_generation_jobs", "science_tool_authorized")
    # 8
    op.drop_column("lesson_versions", "practice_type_hints")
    # 6
    op.drop_column("tutor_turns", "science_tool_call_count")
    op.drop_column("tutor_turns", "science_tool_used")
    op.drop_column("tutor_turns", "code_tool_call_count")
    op.drop_column("tutor_turns", "code_tool_used")
    op.drop_column("tutor_turns", "code_tool_authorized")
    # 5
    op.drop_column("practice_feedback", "coding_public_cases")
    op.drop_column("practice_feedback", "coding_error_categories")
    op.drop_column("practice_feedback", "coding_tests_total")
    op.drop_column("practice_feedback", "coding_tests_passed")
    # 4
    op.drop_column("practice_attempts", "source_code")
    # 3
    op.drop_column("practice_items", "interaction_spec")
    # 2
    op.drop_column("practice_jobs", "code_languages")
    op.drop_column("practice_jobs", "item_type_mode")
    # 1
    op.execute("DROP INDEX IF EXISTS uq_job_tool_auth_practice_cap")
    op.execute("DROP INDEX IF EXISTS uq_job_tool_auth_course_cap")
    op.drop_table("job_tool_authorizations")

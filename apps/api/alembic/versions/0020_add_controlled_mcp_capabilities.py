"""add controlled mcp capabilities

Revision ID: 0020
Revises: 0019

Adds Slice 4 MCP capability tables per Spec 004 §7 and ADR 006 §2.8:

* ``workspace_mcp_policies`` — per-workspace capability enablement
* ``code_lab_runs`` — code execution run records with private I/O
* ``code_lab_jobs`` — async job authority for code runs
* ``tutor_turn_tool_authorizations`` — per-turn science tool authorization
* ``tutor_turn_code_runs`` — turn-to-code-run association (max 1 per turn)

Also adds ``code_lab_job_id`` nullable FK to ``agent_runs``, extending the
4-way "exactly one owner" check constraint.
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# The 4-way "exactly one owner" check constraint for agent_runs.
# Slice 1-3 had 3 owners; Slice 4 adds code_lab_job_id as the 4th.
# ---------------------------------------------------------------------------
AGENT_RUN_ONE_OWNER_NAME = "ck_agent_runs_one_owner"
AGENT_RUN_ONE_OWNER_EXPR = (
    "("
    "(CASE WHEN course_generation_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN tutor_turn_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN practice_job_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN code_lab_job_id IS NOT NULL THEN 1 ELSE 0 END)"
    ") = 1"
)


def upgrade() -> None:
    # ---- workspace_mcp_policies ----
    op.create_table(
        "workspace_mcp_policies",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code_execution_enabled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ---- code_lab_runs ----
    op.create_table(
        "code_lab_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        # Optional navigation grouping — nullable, only for UI categorization
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id", ondelete="SET NULL"), nullable=True),
        # Fixed language
        sa.Column("language", sa.String(10), nullable=False),
        # Private I/O — deleted with the run
        sa.Column("source_code", sa.Text, nullable=False),
        sa.Column("stdin", sa.Text, nullable=False, server_default=""),
        # Execution result
        sa.Column("status", sa.String(30), nullable=False, server_default="queued", index=True),
        sa.Column("compile_output", sa.Text, nullable=False, server_default=""),
        sa.Column("stdout", sa.Text, nullable=False, server_default=""),
        sa.Column("stderr", sa.Text, nullable=False, server_default=""),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("runtime", sa.String(100), nullable=True),
        sa.Column("stdout_truncated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stderr_truncated", sa.Integer, nullable=False, server_default="0"),
        # Server/tool/protocol/schema snapshot
        sa.Column("mcp_server_name", sa.String(100), nullable=True),
        sa.Column("mcp_server_version", sa.String(40), nullable=True),
        sa.Column("mcp_protocol_version", sa.String(20), nullable=True),
        sa.Column("mcp_tool_name", sa.String(100), nullable=True),
        sa.Column("mcp_input_schema_hash", sa.String(64), nullable=True),
        sa.Column("mcp_output_schema_hash", sa.String(64), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ---- code_lab_jobs ----
    op.create_table(
        "code_lab_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("code_lab_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued", index=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(100), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_code_lab_jobs_workspace_key"),
    )

    # ---- tutor_turn_tool_authorizations ----
    op.create_table(
        "tutor_turn_tool_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("capability_id", sa.String(50), nullable=False),
        # Budget
        sa.Column("max_calls", sa.Integer, nullable=False, server_default="3"),
        sa.Column("used_calls", sa.Integer, nullable=False, server_default="0"),
        # Server/protocol/tool/schema snapshot
        sa.Column("mcp_server_name", sa.String(100), nullable=True),
        sa.Column("mcp_protocol_version", sa.String(20), nullable=True),
        sa.Column("mcp_tool_allowlist", sa.Text, nullable=True),  # JSON array of tool names
        sa.Column("mcp_schema_hash", sa.String(64), nullable=True),
        # Timestamps
        sa.Column("authorized_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("turn_id", "capability_id", name="uq_tutor_turn_tool_auth_turn_capability"),
    )

    # ---- tutor_turn_code_runs ----
    op.create_table(
        "tutor_turn_code_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code_lab_run_id", sa.String(36), sa.ForeignKey("code_lab_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("turn_id", name="uq_tutor_turn_code_runs_turn"),  # max 1 per turn
    )

    # ---- mcp_capability_statuses (correction 004 §3/§4) ----
    op.create_table(
        "mcp_capability_statuses",
        sa.Column("capability_id", sa.String(50), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="unavailable"),
        sa.Column("detail", sa.String(200), nullable=True),
        sa.Column("verified_schema_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ttl_seconds", sa.Integer, nullable=False, server_default="30"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("capability_id", name="uq_mcp_capability_statuses_capability"),
    )

    # ---- Extend agent_runs with code_lab_job_id owner ----
    op.add_column(
        "agent_runs",
        sa.Column("code_lab_job_id", sa.String(36), sa.ForeignKey("code_lab_jobs.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_agent_runs_code_lab_job_id", "agent_runs", ["code_lab_job_id"])

    # Replace the 3-way XOR check constraint with the 4-way version
    op.drop_constraint(AGENT_RUN_ONE_OWNER_NAME, "agent_runs", type_="check")
    op.create_check_constraint(AGENT_RUN_ONE_OWNER_NAME, "agent_runs", AGENT_RUN_ONE_OWNER_EXPR)


def downgrade() -> None:
    # Reverse the 4-way check constraint back to 3-way
    THREE_WAY_EXPR = (
        "("
        "(course_generation_job_id IS NOT NULL)::int + "
        "(tutor_turn_id IS NOT NULL)::int + "
        "(practice_job_id IS NOT NULL)::int"
        ") = 1"
    )
    op.drop_constraint(AGENT_RUN_ONE_OWNER_NAME, "agent_runs", type_="check")
    op.create_check_constraint(AGENT_RUN_ONE_OWNER_NAME, "agent_runs", THREE_WAY_EXPR)

    # Drop code_lab_job_id from agent_runs
    op.drop_index("ix_agent_runs_code_lab_job_id", "agent_runs")
    op.drop_column("agent_runs", "code_lab_job_id")

    # Drop new tables in reverse FK order
    op.drop_table("mcp_capability_statuses")
    op.drop_table("tutor_turn_code_runs")
    op.drop_table("tutor_turn_tool_authorizations")
    op.drop_table("code_lab_jobs")
    op.drop_table("code_lab_runs")
    op.drop_table("workspace_mcp_policies")

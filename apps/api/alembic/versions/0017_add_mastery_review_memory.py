"""add learning targets, mastery, review, memory and projection tables

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("course_version_id", sa.String(36), sa.ForeignKey("course_versions.id"), nullable=False),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("target_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lesson_version_id", "target_key", name="uq_learning_targets_version_key"),
    )
    op.create_check_constraint("ck_learning_targets_kind", "learning_targets", "kind IN ('objective', 'lesson_overall')")
    for column in ("workspace_id", "lesson_version_id"):
        op.create_index(f"ix_learning_targets_{column}", "learning_targets", [column])

    op.create_table(
        "practice_item_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("practice_item_id", sa.String(36), sa.ForeignKey("practice_items.id"), nullable=False),
        sa.Column("learning_target_id", sa.String(36), sa.ForeignKey("learning_targets.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("criterion_key", sa.String(100), nullable=True),
        sa.UniqueConstraint("practice_item_id", "learning_target_id", "criterion_key", name="uq_practice_item_targets_item_target_criterion"),
    )
    for column in ("practice_item_id", "learning_target_id", "workspace_id"):
        op.create_index(f"ix_practice_item_targets_{column}", "practice_item_targets", [column])

    op.create_table(
        "learning_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("practice_attempt_id", sa.String(36), sa.ForeignKey("practice_attempts.id"), nullable=False),
        sa.Column("practice_feedback_id", sa.String(36), sa.ForeignKey("practice_feedback.id"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("practice_feedback_id", name="uq_learning_events_feedback"),
    )
    for column in ("workspace_id", "practice_attempt_id"):
        op.create_index(f"ix_learning_events_{column}", "learning_events", [column])

    op.create_table(
        "mastery_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learning_event_id", sa.String(36), sa.ForeignKey("learning_events.id"), nullable=False),
        sa.Column("learning_target_id", sa.String(36), sa.ForeignKey("learning_targets.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("practice_item_id", sa.String(36), sa.ForeignKey("practice_items.id"), nullable=False),
        sa.Column("practice_set_id", sa.String(36), sa.ForeignKey("practice_sets.id"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("is_ai_derived", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("learning_event_id", "learning_target_id", name="uq_mastery_signals_event_target"),
    )
    op.create_check_constraint("ck_mastery_signals_outcome", "mastery_signals", "outcome IN ('positive', 'partial', 'negative')")
    for column in ("learning_event_id", "learning_target_id", "workspace_id"):
        op.create_index(f"ix_mastery_signals_{column}", "mastery_signals", [column])

    op.create_table(
        "mastery_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learning_target_id", sa.String(36), sa.ForeignKey("learning_targets.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("band", sa.String(20), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("distinct_set_count", sa.Integer(), nullable=False),
        sa.Column("projection_score", sa.Float(), nullable=False),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("learning_target_id", name="uq_mastery_states_target"),
    )
    op.create_check_constraint("ck_mastery_states_band", "mastery_states", "band IN ('insufficient', 'needs_review', 'developing', 'secure')")
    for column in ("learning_target_id", "workspace_id"):
        op.create_index(f"ix_mastery_states_{column}", "mastery_states", [column])

    op.create_table(
        "weaknesses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learning_target_id", sa.String(36), sa.ForeignKey("learning_targets.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("first_negative_event_id", sa.String(36), sa.ForeignKey("learning_events.id"), nullable=True),
        sa.Column("last_negative_event_id", sa.String(36), sa.ForeignKey("learning_events.id"), nullable=True),
        sa.Column("memory_suppressed_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("learning_target_id", name="uq_weaknesses_target"),
    )
    op.create_check_constraint("ck_weaknesses_status", "weaknesses", "status IN ('provisional', 'confirmed', 'resolved', 'dismissed')")
    for column in ("learning_target_id", "workspace_id"):
        op.create_index(f"ix_weaknesses_{column}", "weaknesses", [column])

    op.create_table(
        "review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("weakness_id", sa.String(36), sa.ForeignKey("weaknesses.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("last_action_at", sa.DateTime(timezone=True)),
        sa.Column("reopen_count", sa.Integer(), nullable=False),
        sa.Column("reason_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("weakness_id", name="uq_review_items_weakness"),
    )
    for column in ("weakness_id", "workspace_id"):
        op.create_index(f"ix_review_items_{column}", "review_items", [column])

    op.create_table(
        "review_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_item_id", sa.String(36), sa.ForeignKey("review_items.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("snooze_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("review_item_id", "workspace_id"):
        op.create_index(f"ix_review_actions_{column}", "review_actions", [column])

    op.create_table(
        "learning_projection_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_learning_projection_jobs_workspace_key"),
    )
    for column in ("workspace_id", "status", "lease_expires_at", "next_attempt_at"):
        op.create_index(f"ix_learning_projection_jobs_{column}", "learning_projection_jobs", [column])

    op.create_table(
        "learning_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("lesson_version_id", sa.String(36), sa.ForeignKey("lesson_versions.id"), nullable=False),
        sa.Column("learning_target_id", sa.String(36), sa.ForeignKey("learning_targets.id"), nullable=False),
        sa.Column("weakness_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("last_supported_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_check_constraint("ck_learning_memories_kind", "learning_memories", "kind = 'weakness'")
    op.create_check_constraint("ck_learning_memories_status", "learning_memories", "status IN ('active', 'needs_review', 'paused', 'archived')")
    # FK to weaknesses deferred (use_alter in ORM) for clean ordering.
    op.create_foreign_key("fk_learning_memories_weakness", "learning_memories", "weaknesses", ["weakness_id"], ["id"])
    for column in ("workspace_id", "lesson_version_id", "learning_target_id"):
        op.create_index(f"ix_learning_memories_{column}", "learning_memories", [column])
    op.create_index(
        "uq_learning_memories_current_target",
        "learning_memories",
        ["learning_target_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'archived'"),
    )

    op.create_table(
        "learning_memory_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learning_memory_id", sa.String(36), sa.ForeignKey("learning_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("learning_event_id", sa.String(36), sa.ForeignKey("learning_events.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.UniqueConstraint("learning_memory_id", "learning_event_id", name="uq_learning_memory_sources_memory_event"),
    )
    for column in ("learning_memory_id", "workspace_id"):
        op.create_index(f"ix_learning_memory_sources_{column}", "learning_memory_sources", [column])

    op.create_table(
        "learning_memory_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learning_memory_id", sa.String(36), sa.ForeignKey("learning_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before_hash", sa.String(64)),
        sa.Column("after_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("learning_memory_id", "workspace_id"):
        op.create_index(f"ix_learning_memory_revisions_{column}", "learning_memory_revisions", [column])

    op.create_table(
        "learning_memory_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("tutor_use_enabled", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", name="uq_learning_memory_policies_workspace"),
    )
    op.create_index("ix_learning_memory_policies_workspace_id", "learning_memory_policies", ["workspace_id"])

    # §7: First create LearningTargets for all existing Lesson Versions.
    # objective_1..N from learning_objectives JSON + lesson_overall fallback.
    op.execute(sa.text("""
        INSERT INTO learning_targets (id, workspace_id, course_id, course_version_id, lesson_id, lesson_version_id, target_key, title, kind, created_at)
        SELECT
            md5(lv.id::text || '_objective_' || obj.idx::text),
            lv.workspace_id, cv.course_id, lv.course_version_id, lv.lesson_id, lv.id,
            'objective_' || obj.idx::text,
            LEFT(obj.val::text, 300),
            'objective',
            NOW()
        FROM lesson_versions lv
        JOIN course_versions cv ON cv.id = lv.course_version_id
        JOIN courses c ON c.id = cv.course_id
        CROSS JOIN LATERAL (
            SELECT row_number() OVER () AS idx, elem::text AS val
            FROM json_array_elements(lv.learning_objectives) AS elem
        ) AS obj
        WHERE json_array_length(lv.learning_objectives) > 0
    """))
    # Always create lesson_overall for every Lesson Version.
    op.execute(sa.text("""
        INSERT INTO learning_targets (id, workspace_id, course_id, course_version_id, lesson_id, lesson_version_id, target_key, title, kind, created_at)
        SELECT
            md5(lv.id::text || '_lesson_overall'),
            lv.workspace_id, cv.course_id, lv.course_version_id, lv.lesson_id, lv.id,
            'lesson_overall', 'Lesson Overall', 'lesson_overall', NOW()
        FROM lesson_versions lv
        JOIN course_versions cv ON cv.id = lv.course_version_id
    """))
    # Now backfill: existing practice items without target mapping get lesson_overall.
    op.execute(sa.text(
        "INSERT INTO practice_item_targets (id, practice_item_id, learning_target_id, workspace_id, criterion_key) "
        "SELECT "
        "  md5(pi.id::text), "
        "  pi.id, "
        "  lt.id, "
        "  pi.workspace_id, "
        "  NULL "
        "FROM practice_items pi "
        "JOIN practice_sets ps ON pi.practice_set_id = ps.id "
        "JOIN learning_targets lt ON lt.lesson_version_id = ps.lesson_version_id AND lt.target_key = 'lesson_overall' "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM practice_item_targets pit WHERE pit.practice_item_id = pi.id"
        ")"
    ))


def downgrade() -> None:
    op.drop_table("learning_memory_policies")
    op.drop_table("learning_memory_revisions")
    op.drop_table("learning_memory_sources")
    op.drop_index("ix_learning_memories_learning_target_id", table_name="learning_memories")
    op.drop_index("ix_learning_memories_lesson_version_id", table_name="learning_memories")
    op.drop_index("ix_learning_memories_workspace_id", table_name="learning_memories")
    op.drop_constraint("fk_learning_memories_weakness", "learning_memories", type_="foreignkey")
    op.drop_table("learning_memories")
    for column in ("workspace_id", "status", "lease_expires_at", "next_attempt_at"):
        op.drop_index(f"ix_learning_projection_jobs_{column}", table_name="learning_projection_jobs")
    op.drop_table("learning_projection_jobs")
    op.drop_table("review_actions")
    op.drop_table("review_items")
    op.drop_table("weaknesses")
    op.drop_index("ix_mastery_states_workspace_id", table_name="mastery_states")
    op.drop_index("ix_mastery_states_learning_target_id", table_name="mastery_states")
    op.drop_table("mastery_states")
    op.drop_index("ix_mastery_signals_workspace_id", table_name="mastery_signals")
    op.drop_index("ix_mastery_signals_learning_target_id", table_name="mastery_signals")
    op.drop_index("ix_mastery_signals_learning_event_id", table_name="mastery_signals")
    op.drop_table("mastery_signals")
    op.drop_table("learning_events")
    for column in ("practice_item_id", "learning_target_id", "workspace_id"):
        op.drop_index(f"ix_practice_item_targets_{column}", table_name="practice_item_targets")
    op.drop_table("practice_item_targets")
    op.drop_index("ix_learning_targets_lesson_version_id", table_name="learning_targets")
    op.drop_index("ix_learning_targets_workspace_id", table_name="learning_targets")
    op.drop_table("learning_targets")

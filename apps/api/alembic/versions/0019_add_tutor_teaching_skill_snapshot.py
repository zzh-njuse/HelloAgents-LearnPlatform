"""add tutor teaching skill snapshot

Revision ID: 0019
Revises: 0018

Adds the immutable teaching-skill snapshot columns to ``tutor_turns``:

* ``teaching_skill_id``      — the resolved skill id
* ``teaching_skill_version`` — the resolved skill version
* ``teaching_skill_hash``    — SHA-256 of the normalized skill body

Slice 3 new turns always populate all three (the server resolves the single
current published skill). Slice 3 historical turns leave all three NULL and keep
using the legacy baseline path. A check constraint enforces "all NULL or all
non-NULL" so a turn can never carry a partial/half-upgraded snapshot.
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

#: The check-constraint expression. Exposed as a constant so the migration and
#: its unit test share one source of truth (SQLite cannot ALTER-add a constraint,
#: so the test embeds this expression in a fresh table to validate its semantics;
#: Postgres applies it via ALTER in :func:`upgrade`).
SNAPSHOT_ALL_OR_NONE_EXPR = (
    "("
    "(teaching_skill_id IS NULL AND teaching_skill_version IS NULL AND teaching_skill_hash IS NULL) "
    "OR "
    "(teaching_skill_id IS NOT NULL AND teaching_skill_version IS NOT NULL AND teaching_skill_hash IS NOT NULL)"
    ")"
)
CONSTRAINT_NAME = "ck_tutor_turns_teaching_skill_snapshot"


def upgrade() -> None:
    op.add_column("tutor_turns", sa.Column("teaching_skill_id", sa.String(100), nullable=True))
    op.add_column("tutor_turns", sa.Column("teaching_skill_version", sa.String(40), nullable=True))
    op.add_column("tutor_turns", sa.Column("teaching_skill_hash", sa.String(64), nullable=True))
    op.create_check_constraint(CONSTRAINT_NAME, "tutor_turns", SNAPSHOT_ALL_OR_NONE_EXPR)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "tutor_turns", type_="check")
    op.drop_column("tutor_turns", "teaching_skill_hash")
    op.drop_column("tutor_turns", "teaching_skill_version")
    op.drop_column("tutor_turns", "teaching_skill_id")

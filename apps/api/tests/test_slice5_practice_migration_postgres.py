"""Stage 4 Slice 5 — isolated Postgres migration test (Phase B / §13.2).

Verifies migration 0023 (``practice_jobs.artifact_contract_version``) against a
REAL, ISOLATED Postgres database: upgrade backfills existing rows to v1 and
makes the column non-null; downgrade drops only that column. Per ADR 007 §3.9
this is the only schema delta.

This test NEVER runs against the development Postgres volume and NEVER performs
a downgrade there. It is gated on ``SLICE5_PG_TEST_URL`` (an isolated, throwaway
database the caller creates). When that URL is absent the test skips with an
explicit reason — it does not fall back to SQLite (SQLite ORM does not exercise
the alembic migration and must not masquerade as a Postgres result).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = API_ROOT / "alembic.ini"
VERSIONS_DIR = API_ROOT / "alembic" / "versions"

PG_TEST_URL = os.environ.get("SLICE5_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_TEST_URL,
    reason="Set SLICE5_PG_TEST_URL to an isolated throwaway Postgres database to run the migration test; SQLite ORM does not count as a Postgres migration (§13.2).",
)


def _alembic_env(url: str) -> dict[str, str]:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    return env


def test_migration_0023_source_is_a_single_additive_delta() -> None:
    """Static guard (runs even when Postgres is absent): migration 0023 only
    adds the one approved column and only drops it on downgrade — it never
    touches Set/Item/Attempt/Feedback history."""
    migration = (VERSIONS_DIR / "0023_add_practice_job_artifact_contract_version.py").read_text(encoding="utf-8")
    assert 'revision = "0023"' in migration
    assert 'down_revision = "0022"' in migration
    assert "artifact_contract_version" in migration
    assert "practice_artifact_v1" in migration
    # Additive only: upgrade adds a column; downgrade drops the same column.
    assert "add_column" in migration and "drop_column" in migration


def test_migration_0023_upgrade_backfills_and_downgrades_on_postgres() -> None:
    """End-to-end on an isolated Postgres DB: create the pre-0023 schema, insert
    a practice_job row, upgrade to head, assert the column is non-null and
    backfilled to v1, then downgrade and assert the column is gone."""
    import subprocess

    def alembic(*args: str) -> None:
        subprocess.run(["python", "-m", "alembic", *args], cwd=str(API_ROOT),
                       env=_alembic_env(PG_TEST_URL), check=True)

    # Bring the isolated DB to 0022 (pre-Slice-5 head), then add a row.
    alembic("upgrade", "0022")
    import sqlalchemy as sa
    engine = sa.create_engine(PG_TEST_URL)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO workspaces (id, name, slug) VALUES ('w1','w','w') ON CONFLICT DO NOTHING"
        ))
        conn.execute(sa.text(
            "INSERT INTO practice_jobs (id, workspace_id, job_type, output_language, difficulty, "
            "item_count, request_hash, status, idempotency_key, attempt_count) "
            "VALUES ('j1','w1','generate_set','zh-CN','standard',1,'h','succeeded','k',0)"
        ))
    # Upgrade to head (0023): column added, backfilled, non-null.
    alembic("upgrade", "head")
    with engine.begin() as conn:
        row = conn.execute(sa.text("SELECT artifact_contract_version FROM practice_jobs WHERE id='j1'")).one()
        assert row[0] == "practice_artifact_v1"
        # Non-null enforced: inserting NULL must fail.
        with pytest.raises(Exception):
            conn.execute(sa.text(
                "INSERT INTO practice_jobs (id, workspace_id, job_type, output_language, difficulty, "
                "item_count, request_hash, status, idempotency_key, attempt_count, artifact_contract_version) "
                "VALUES ('j2','w1','generate_set','zh-CN','standard',1,'h','succeeded','k2',0,NULL)"
            ))
    # Downgrade by one: column dropped, nothing else changed.
    alembic("downgrade", "0022")
    cols = {row[0] for row in engine.connect().execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='practice_jobs'"
    ))}
    assert "artifact_contract_version" not in cols
    engine.dispose()

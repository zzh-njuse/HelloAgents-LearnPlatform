"""Postgres-only cross-transaction final-authority test (corr 002/3.2).

On SQLite a single write transaction locks the whole database, so a second
session cannot commit a change while the executing session's transaction is
open. Postgres MVCC allows it, which is exactly the race the final authority
must close: a separate transaction that deletes/republishes/degrades a source
after the provider returned must be observed by the committing transaction, not
served from a stale identity-map cache.

These tests build a throwaway database and never touch the user's database or
volume. They skip automatically when the local development Postgres is not
reachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

psycopg = pytest.importorskip("psycopg")

PG_ADMIN = "postgresql://hello_agents:hello_agents@localhost:55432/postgres"
PG_TEMPLATE = "postgresql+psycopg://hello_agents:hello_agents@localhost:55432/{name}"


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(PG_ADMIN, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="local Postgres not reachable for cross-transaction authority tests")


@pytest.fixture()
def pg_engine():
    name = f"stage4_tutor_auth_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()
    from learn_platform_api.db.base import Base
    import learn_platform_api.db.models  # noqa: F401 - register metadata

    engine = create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()


def _settings():
    return SimpleNamespace(
        product_generation_api_key=None, product_generation_base_url="https://offline.invalid",
        product_generation_model="offline-fake", product_generation_timeout_seconds=45.0,
        tutor_max_evidence_tokens=8_000, tutor_max_output_tokens=2_000,
        tutor_skill_max_evidence_tokens=10_000, tutor_skill_max_output_tokens=3_000,
    )


def _seed(db, snapshot):
    from learn_platform_api.db.models import (Course, CourseSection, CourseVersion, CourseVersionSource,
        DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument, TutorSession, TutorTurn, Workspace)
    ws = Workspace(name="auth", slug="auth"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="Cathedral mode uses central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=60, page_start=1, page_end=1); db.add(chunk); db.flush()
    course = Course(workspace_id=ws.id, title="c", goal="g"); db.add(course); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="c"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    src = CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id); db.add(src)
    session = TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)); db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status="running", question="q", scope="course", history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], worker_id="pg-worker", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300)); db.add(turn); db.commit()
    return turn, chunk, src


def test_final_authority_observes_cross_transaction_source_degrade(pg_engine):
    """A source degraded by a SEPARATE committed transaction after the provider
    returned must be observed by the executing transaction's final authority
    (never served from a stale identity-map cache)."""
    from learn_platform_api.db.models import CourseVersionSource, SourceDocument, TutorSession
    from learn_platform_api.services import tutor_generation
    from learn_platform_api.services.tutor import resolve_teaching_skill_snapshot

    snapshot = resolve_teaching_skill_snapshot()
    db = sessionmaker(bind=pg_engine, expire_on_commit=False)()
    try:
        turn, chunk, src = _seed(db, snapshot)
        plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
        answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}

        def degrade_in_other_transaction(*_a, **_k):
            other = sessionmaker(bind=pg_engine)()
            try:
                session_obj = other.get(TutorSession, turn.session_id)
                source = other.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == session_obj.course_version_id))
                other.get(SourceDocument, source.document_id).lifecycle_status = "deleted"
                other.commit()
            finally:
                other.close()
            return answer, {"input_tokens": 5, "output_tokens": 5}

        original_search = tutor_generation._search
        tutor_generation._search = lambda *_a, **_k: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)})
        tutor_generation.call_provider = degrade_in_other_transaction
        try:
            with pytest.raises(ValueError) as exc_info:
                tutor_generation.execute_tutor_turn(db, _settings(), turn, worker_id="pg-worker", lease_lost=None)
            assert str(exc_info.value) == "source_snapshot_stale"
        finally:
            tutor_generation._search = original_search
            from learn_platform_api.services.course_generation import call_provider as real_call_provider
            tutor_generation.call_provider = real_call_provider
        db.rollback()
    finally:
        db.close()


def test_final_authority_locks_block_concurrent_update_until_commit(pg_engine):
    """While the final-authority boundary holds the authoritative row locks, a
    concurrent transaction's conflicting UPDATE on a locked row must block and
    time out (it cannot land before the owning transaction commits). After the
    owner commits, the concurrent update succeeds. Proves the TOCTOU window is
    closed on real Postgres (corr 003/3.2)."""
    from learn_platform_api.db.models import CourseVersionSource, TutorSession
    from learn_platform_api.services import tutor_generation
    from learn_platform_api.services.tutor import resolve_teaching_skill_snapshot

    snapshot = resolve_teaching_skill_snapshot()
    owner = sessionmaker(bind=pg_engine, expire_on_commit=False)()
    try:
        turn, chunk, src = _seed(owner, snapshot)
        ledger = {"e1": (chunk, src)}

        # The owning transaction runs the final authority, acquiring FOR UPDATE
        # locks on Workspace/Turn/Session/Course and the ledger sources. It does
        # NOT commit yet, so the locks are held.
        tutor_generation._assert_final_authority(owner, turn, "pg-worker", None, ledger)

        # A concurrent connection attempts to degrade a locked ledger source with
        # a short lock_timeout; it must time out, not update.
        source = owner.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == owner.get(TutorSession, turn.session_id).course_version_id))
        db_url = f"postgresql://hello_agents:hello_agents@localhost:55432/{pg_engine.url.database}"
        contender = psycopg.connect(db_url, autocommit=False)
        try:
            contender.execute("SET lock_timeout = '2s'")
            try:
                contender.execute("UPDATE source_documents SET lifecycle_status = 'deleted' WHERE id = %s", (source.document_id,))
                contender.commit()
                raised = False
            except psycopg.errors.LockNotAvailable:
                contender.rollback(); raised = True
            except psycopg.errors.QueryCanceled:
                contender.rollback(); raised = True
            assert raised, "concurrent update on a locked source row unexpectedly succeeded before commit"
        finally:
            contender.close()

        # Owner commits, releasing the locks; the same update now succeeds.
        owner.commit()
        after = psycopg.connect(db_url, autocommit=True)
        try:
            after.execute("UPDATE source_documents SET lifecycle_status = 'deleted' WHERE id = %s", (source.document_id,))
        finally:
            after.close()
    finally:
        owner.close()

"""Real Postgres deletion tests for the practice circular foreign keys.

SQLite does not enforce foreign keys, so the PracticeJob <-> {PracticeSet,
PracticeAttempt} cycle can only be proven on Postgres. These tests build a
throwaway database, enable FK enforcement, and exercise every deletion path.
They skip automatically when the local Postgres used for development is not
reachable, and never touch the user's existing database or volume.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
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


pytestmark = pytest.mark.skipif(not _pg_available(), reason="local Postgres not reachable for FK deletion tests")


@pytest.fixture()
def pg_db():
    name = f"stage4_del_{uuid4().hex[:12]}"
    admin = psycopg.connect(PG_ADMIN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.execute(f"CREATE DATABASE {name}")
    admin.close()
    from learn_platform_api.db.base import Base
    import learn_platform_api.db.models  # noqa: F401 - register metadata

    engine = create_engine(PG_TEMPLATE.format(name=name))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        admin = psycopg.connect(PG_ADMIN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.close()


def _seed(pg_db):
    from learn_platform_api.db.models import (
        Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
        Lesson, LessonVersion, PracticeAttempt, PracticeFeedback, PracticeItem, PracticeItemCitation,
        PracticeJob, PracticeJobSource, PracticeSet, SourceDocument, Workspace,
    )
    ws = Workspace(name="pg", slug="pg"); pg_db.add(ws); pg_db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); pg_db.add(doc); pg_db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); pg_db.add(ver); pg_db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="content", content_hash="b" * 64, start_offset=0, end_offset=7, page_start=1, page_end=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); pg_db.add_all([chunk, course]); pg_db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); pg_db.add(cv); pg_db.flush(); course.current_active_version_id = cv.id
    pg_db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); pg_db.add(section); pg_db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); pg_db.add(lesson); pg_db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["o"], blocks=[]); pg_db.add(lv); pg_db.flush(); lesson.current_published_version_id = lv.id
    gen_job = PracticeJob(workspace_id=ws.id, job_type="generate_set", course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN", difficulty="standard", item_count=1, request_hash="0" * 64, status="succeeded", idempotency_key="g", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    pg_db.add(gen_job); pg_db.flush()
    pg_db.add(PracticeJobSource(practice_job_id=gen_job.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    practice_set = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, practice_job_id=gen_job.id, output_language="zh-CN", difficulty="standard", item_count=1, generation_config={}, lifecycle_status="active")
    pg_db.add(practice_set); pg_db.flush(); gen_job.practice_set_id = practice_set.id
    item = PracticeItem(practice_set_id=practice_set.id, workspace_id=ws.id, ordinal=0, item_type="short_answer", stem="s", options=None, answer_spec={"reference_answer": "r", "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100, "citation_ids": ["e1"]}], "citation_ids": ["e1"]})
    pg_db.add(item); pg_db.flush()
    pg_db.add(PracticeItemCitation(practice_item_id=item.id, workspace_id=ws.id, citation_key="e1", document_id=doc.id, document_version_id=ver.id, document_chunk_id=chunk.id))
    pg_db.commit()
    return ws, practice_set, item, gen_job


def _count(pg_db, model) -> int:
    from sqlalchemy import func, select
    return int(pg_db.execute(select(func.count(model.id))).scalar() or 0)


def test_cleanup_set_with_generation_and_grading_jobs_on_postgres(pg_db) -> None:
    from learn_platform_api.db.models import (
        AgentRun, AgentToolCall, PracticeAttempt, PracticeFeedback, PracticeItem, PracticeItemCitation, PracticeJob, PracticeJobSource, PracticeSet,
    )
    from learn_platform_api.services.practice import cleanup_set
    ws, practice_set, item, gen_job = _seed(pg_db)
    # Add a grading job + attempt + feedback referencing the item.
    attempt = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="short_answer", answer_payload={"text": "a"}, idempotency_key="a", status="succeeded", completed_at=datetime.now(timezone.utc))
    pg_db.add(attempt); pg_db.flush()
    grade_job = PracticeJob(workspace_id=ws.id, job_type="grade_attempt", practice_attempt_id=attempt.id, output_language="zh-CN", difficulty="standard", item_count=1, request_hash="0" * 64, status="succeeded", idempotency_key="gr", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    pg_db.add(grade_job); pg_db.flush(); attempt.practice_job_id = grade_job.id
    pg_db.add(PracticeFeedback(practice_attempt_id=attempt.id, workspace_id=ws.id, verdict="correct", score=100, criterion_results=None, feedback_blocks=[{"block_key": "b", "type": "explanation", "text": "ok", "citation_ids": []}], is_ai_graded=1, created_at=datetime.now(timezone.utc)))
    pg_db.add(AgentRun(practice_job_id=gen_job.id, workspace_id=ws.id, role="exercise_author", attempt_number=1, status="succeeded"))
    pg_db.add(AgentRun(practice_job_id=grade_job.id, workspace_id=ws.id, role="answer_grader", attempt_number=1, status="succeeded"))
    pg_db.commit()

    practice_set.lifecycle_status = "deleting"; pg_db.commit()
    assert cleanup_set(pg_db, practice_set.id) is True

    for model in [PracticeFeedback, PracticeAttempt, PracticeItemCitation, PracticeItem, PracticeJobSource, PracticeJob, PracticeSet]:
        assert _count(pg_db, model) == 0, f"{model.__name__} residue after cleanup_set"
    # AgentRun/AgentToolCall owned by the deleted jobs are also gone.
    assert _count(pg_db, AgentRun) == 0
    assert _count(pg_db, AgentToolCall) == 0


def test_delete_attempt_on_postgres(pg_db) -> None:
    from learn_platform_api.db.models import PracticeAttempt, PracticeFeedback, PracticeJob
    from learn_platform_api.services.practice import delete_attempt
    ws, _set, item, _gen = _seed(pg_db)
    attempt = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="short_answer", answer_payload={"text": "a"}, idempotency_key="a", status="succeeded", completed_at=datetime.now(timezone.utc))
    pg_db.add(attempt); pg_db.flush()
    grade_job = PracticeJob(workspace_id=ws.id, job_type="grade_attempt", practice_attempt_id=attempt.id, output_language="zh-CN", difficulty="standard", item_count=1, request_hash="0" * 64, status="succeeded", idempotency_key="gr", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    pg_db.add(grade_job); pg_db.flush(); attempt.practice_job_id = grade_job.id
    pg_db.add(PracticeFeedback(practice_attempt_id=attempt.id, workspace_id=ws.id, verdict="correct", score=100, criterion_results=None, feedback_blocks=[], is_ai_graded=1, created_at=datetime.now(timezone.utc)))
    pg_db.commit()
    assert delete_attempt(pg_db, None, ws.id, attempt.id) is True
    assert _count(pg_db, PracticeAttempt) == 0
    assert _count(pg_db, PracticeFeedback) == 0
    # The grading job for that attempt is removed; the generation job remains.
    assert _count(pg_db, PracticeJob) == 1


def test_hard_delete_workspace_practice_on_postgres(pg_db) -> None:
    from learn_platform_api.db.models import PracticeSet
    from learn_platform_api.services.practice import hard_delete_workspace_practice
    ws, _set, _item, _gen = _seed(pg_db)
    hard_delete_workspace_practice(pg_db, ws.id)
    assert _count(pg_db, PracticeSet) == 0
    # Idempotent: a second call must not raise (cycle already clear).
    hard_delete_workspace_practice(pg_db, ws.id)


def test_postgres_enforces_foreign_keys(pg_db) -> None:
    """Sanity: the throwaway database really enforces FKs (else the above prove nothing)."""
    row = pg_db.execute(text("SHOW server_version")).scalar()
    assert row  # connected
    with pytest.raises(Exception):
        # Inserting a practice_set pointing at a non-existent workspace must fail.
        pg_db.execute(text("INSERT INTO practice_sets (id, workspace_id, course_id, course_version_id, lesson_id, lesson_version_id, output_language, difficulty, item_count, generation_config, lifecycle_status, created_at) VALUES ('x', 'nope', 'nope', 'nope', 'nope', 'nope', 'zh-CN', 'standard', 1, '{}', 'active', now())"))
        pg_db.commit()

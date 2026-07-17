"""Correction 003 focused tests: failed step_count, owner/lease matrix, usage,
retry_wait timing. Uses fake provider + SQLite + shared-session worker pattern.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from learn_platform_api.db.models import (
    AgentRun, AgentToolCall, Course, CourseSection, CourseVersion, CourseVersionSource,
    DocumentChunk, DocumentVersion, Lesson, LessonVersion, PracticeAttempt, PracticeFeedback,
    PracticeItem, PracticeItemCitation, PracticeJob, PracticeSet, SourceDocument, Workspace,
)
from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
from learn_platform_api.services import practice, practice_generation
from learn_platform_api.services.practice_generation import execute_generation, execute_grading
from learn_platform_api.settings import get_settings

TW = "tw"


class _SharedSession:
    def __init__(self, session): self._s = session
    def __enter__(self): return self._s
    def __exit__(self, *_a): return False


def _reader(db):
    ws = Workspace(name="c3", slug="c3"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=("c" * 32)[:36], document_version_id=ver.id, ordinal=0, content="Binary search halves a sorted interval.", content_hash="b" * 64, start_offset=0, end_offset=36, page_start=1, page_end=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    sec = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(sec); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=sec.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["o"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id; db.commit()
    return ws, course, cv, lesson, lv, chunk, doc, ver


def _ev(chunk, doc, ver):
    return lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=doc.id, document_version_id=ver.id, chunk_id=chunk.id, document_name=doc.display_name, heading_path=[], start_offset=0, end_offset=5))])


def _artifact():
    return {"items": [
        {"item_key": "q1", "item_type": "single_choice", "stem": "s", "citation_ids": ["e1"], "options": [{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["e1"]}, {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["e1"]}]},
        {"item_key": "q2", "item_type": "short_answer", "stem": "s", "citation_ids": ["e1"], "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100, "citation_ids": ["e1"]}], "reference_answer": "r"},
    ]}


def _gen_job(db, ws, course, cv, lesson, lv, n=2):
    class P: pass
    P.item_count = n; P.difficulty = "standard"; P.output_language = "zh-CN"
    return practice.create_generation_job(db, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, P(), f"g-{id(db)}")


def _claim(db, job):
    job.status = "running"; job.attempt_count = max(1, job.attempt_count + 1); job.worker_id = TW
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=300); db.commit()


# --------------------------------------------------------------------------- #
# §2: failed AgentRun step_count precision
# --------------------------------------------------------------------------- #

def test_failed_step_count_plan_only(db_session: Session, monkeypatch) -> None:
    """Plan provider call fails: the worker captures step_count==1 before rollback."""
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv = _reader(db_session)[:5]
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "call_provider", _raise(ValueError("provider_unavailable")))
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 1)
    practice_workers.run_practice_job(job.id); db_session.commit()
    runs = list(db_session.query(AgentRun).filter_by(practice_job_id=job.id, status="failed"))
    assert runs and runs[0].step_count == 1, f"plan-only failure step_count={runs[0].step_count if runs else 'no run'}"


def test_failed_step_count_plan_plus_search(db_session: Session, monkeypatch) -> None:
    """Plan succeeds, retrieval fails: the worker captures step_count==2."""
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: ({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(practice_generation, "retrieve", _raise(RuntimeError("retrieval crashed")))
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 1)
    practice_workers.run_practice_job(job.id); db_session.commit()
    runs = list(db_session.query(AgentRun).filter_by(practice_job_id=job.id, status="failed"))
    assert runs and runs[0].step_count == 2, f"plan+search failure step_count={runs[0].step_count if runs else 'no run'}"


def test_success_step_count_exact(db_session: Session, monkeypatch) -> None:
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", _ev(chunk, doc, ver))
    _p = iter([({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}), (_artifact(), {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(_p))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 2); _claim(db_session, job)
    execute_generation(db_session, get_settings(), job, worker_id=TW); db_session.commit()
    run = db_session.query(AgentRun).filter_by(practice_job_id=job.id).one()
    assert run.step_count == 3  # plan + 1 search + 1 submit


# --------------------------------------------------------------------------- #
# §3: owner/lease final-commit matrix (generation)
# --------------------------------------------------------------------------- #

GEN_MUTATIONS = ["owner_replaced", "lease_expired", "status_reset", "lesson_changed", "course_changed", "source_degraded"]


@pytest.mark.parametrize("mutation", GEN_MUTATIONS)
def test_generation_final_authority_blocks(db_session: Session, monkeypatch, mutation: str) -> None:
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", _ev(chunk, doc, ver))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 2); _claim(db_session, job)

    cc = [0]
    def provider_hook(*_a, **_k):
        cc[0] += 1
        if cc[0] == 1:
            return ({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1})
        _ZERO = "00000000-0000-0000-0000-000000000000"
        if mutation == "owner_replaced":
            db_session.execute(update(PracticeJob).where(PracticeJob.id == job.id).values(worker_id="other")); db_session.flush()
        elif mutation == "owner_replaced_external":
            ext = sessionmaker(bind=db_session.bind)(); ext.execute(update(PracticeJob).where(PracticeJob.id == job.id).values(worker_id="other")); ext.commit(); ext.close()
        elif mutation == "lease_expired":
            db_session.execute(update(PracticeJob).where(PracticeJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))); db_session.flush()
        elif mutation == "status_reset":
            db_session.execute(update(PracticeJob).where(PracticeJob.id == job.id).values(status="queued")); db_session.flush()
        elif mutation == "lesson_changed":
            db_session.execute(update(Lesson).where(Lesson.id == lesson.id).values(current_published_version_id=_ZERO)); db_session.flush()
        elif mutation == "course_changed":
            db_session.execute(update(Course).where(Course.id == course.id).values(current_active_version_id=_ZERO)); db_session.flush()
        elif mutation == "source_degraded":
            db_session.execute(update(SourceDocument).where(SourceDocument.id == doc.id).values(lifecycle_status="deleted")); db_session.flush()
        return (_artifact(), {"input_tokens": 1, "output_tokens": 1})
    monkeypatch.setattr(practice_generation, "call_provider", provider_hook)

    try:
        execute_generation(db_session, get_settings(), job, worker_id=TW)
        pytest.fail("authority should block")
    except ValueError:
        db_session.rollback()
    assert db_session.query(PracticeSet).filter_by(workspace_id=ws.id).count() == 0
    assert db_session.get(PracticeJob, job.id).status != "succeeded"


# --------------------------------------------------------------------------- #
# §4: token usage missing-combination tests
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("plan_u,submit_u,exp_in,exp_out", [
    ({"input_tokens": 2, "output_tokens": 2}, {"input_tokens": 10, "output_tokens": 20}, 12, 22),
    ({}, {}, None, None),
    ({"output_tokens": 2}, {"input_tokens": 10, "output_tokens": 20}, None, 22),
    ({"input_tokens": 5}, {"input_tokens": 5}, 10, None),
])
def test_generation_usage(db_session: Session, monkeypatch, plan_u, submit_u, exp_in, exp_out) -> None:
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", _ev(chunk, doc, ver))
    _p = iter([({"queries": ["q"]}, plan_u), (_artifact(), submit_u)])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(_p))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 2); _claim(db_session, job)
    execute_generation(db_session, get_settings(), job, worker_id=TW); db_session.commit()
    run = db_session.query(AgentRun).filter_by(practice_job_id=job.id).one()
    assert run.input_tokens == exp_in, f"input {run.input_tokens} != {exp_in}"
    assert run.output_tokens == exp_out, f"output {run.output_tokens} != {exp_out}"
    j = db_session.get(PracticeJob, job.id)
    assert j.input_tokens == exp_in and j.output_tokens == exp_out


# --------------------------------------------------------------------------- #
# §5: retry_wait claim timing
# --------------------------------------------------------------------------- #

def test_retry_wait_not_due_no_claim(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv = _reader(db_session)[:5]
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 1)
    job.status = "retry_wait"; job.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1); job.attempt_count = 1; db_session.commit()
    before = (job.status, job.worker_id, job.attempt_count, job.next_attempt_at)
    practice_workers.run_practice_job(job.id); db_session.commit()
    r = db_session.get(PracticeJob, job.id)
    assert (r.status, r.worker_id, r.attempt_count) == (before[0], before[1], before[2])


def test_retry_wait_due_claimed_once(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import practice_workers
    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", _ev(chunk, doc, ver))
    calls = []
    _p = iter([({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}), (_artifact(), {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: (calls.append(1), next(_p))[1])
    monkeypatch.setattr(practice_workers, "SessionLocal", lambda: _SharedSession(db_session))
    job = _gen_job(db_session, ws, course, cv, lesson, lv, 1)
    job.status = "retry_wait"; job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1); job.attempt_count = 1; db_session.commit()
    practice_workers.run_practice_job(job.id); db_session.commit()
    assert db_session.get(PracticeJob, job.id).status == "succeeded"
    assert db_session.get(PracticeJob, job.id).attempt_count == 2
    calls_before = len(calls)
    practice_workers.run_practice_job(job.id); db_session.commit()  # duplicate delivery
    assert len(calls) == calls_before
    assert db_session.get(PracticeJob, job.id).attempt_count == 2
    assert db_session.query(PracticeSet).filter_by(workspace_id=ws.id).count() == 1


def _raise(exc):
    def _r(*_a, **_k):
        raise exc
    return _r

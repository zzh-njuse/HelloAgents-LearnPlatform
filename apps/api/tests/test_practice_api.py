from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun, Course, CourseGenerationJob, CourseSection, CourseVersion, CourseVersionSource,
    DocumentChunk, DocumentVersion, Lesson, LessonVersion, PracticeAttempt, PracticeFeedback,
    PracticeItem, PracticeItemCitation, PracticeJob, PracticeJobSource, PracticeSet, SourceDocument, Workspace,
)
from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
from learn_platform_api.services import practice_generation
from learn_platform_api.services.practice_generation import execute_generation, execute_grading
from learn_platform_api.settings import get_settings

PRACTICE_FORBIDDEN = {
    "answer_spec", "correct_option_key", "option_rationales", "is_correct", "rationale",
    "reference_answer", "rubric", "prompt", "evidence", "content",
    "provider", "model", "base_url", "api_key", "input_hash", "tool_input",
}


def _collect_keys(value, into=None):
    into = set() if into is None else into
    if isinstance(value, dict):
        into.update(value.keys())
        for nested in value.values():
            _collect_keys(nested, into)
    elif isinstance(value, list):
        for nested in value:
            _collect_keys(nested, into)
    return into


def _reader_fixture(db: Session):
    workspace = Workspace(name="Practice workspace", slug="practice-workspace")
    db.add(workspace); db.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="guide.md")
    db.add(document); db.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="guide.md", mime_type="text/markdown", byte_size=10, sha256="a" * 64, original_storage_uri="test")
    db.add(version); db.flush(); document.current_version_id = version.id
    chunk = DocumentChunk(id="11111111-1111-1111-1111-111111111111", document_version_id=version.id, ordinal=0, content="Binary search halves a sorted interval until the target is found.", content_hash="b" * 64, start_offset=0, end_offset=64, page_start=3, page_end=3)
    course = Course(workspace_id=workspace.id, title="Algorithms", goal="Learn search")
    db.add_all([chunk, course]); db.flush()
    course_version = CourseVersion(course_id=course.id, workspace_id=workspace.id, version_number=1, status="active", title=course.title)
    db.add(course_version); db.flush(); course.current_active_version_id = course_version.id
    db.add(CourseVersionSource(course_version_id=course_version.id, workspace_id=workspace.id, document_id=document.id, document_version_id=version.id))
    section = CourseSection(course_version_id=course_version.id, workspace_id=workspace.id, ordinal=0, title="Search", objective="Understand search")
    db.add(section); db.flush()
    lesson = Lesson(course_version_id=course_version.id, course_section_id=section.id, workspace_id=workspace.id, ordinal=0, title="Binary search", objective="Explain halving")
    db.add(lesson); db.flush()
    lesson_version = LessonVersion(lesson_id=lesson.id, course_version_id=course_version.id, workspace_id=workspace.id, version_number=1, status="published", title=lesson.title, learning_objectives=["Explain halving"], blocks=[{"block_key": "p1", "type": "paragraph", "text": chunk.content, "citation_ids": ["c1"]}])
    db.add(lesson_version); db.flush(); lesson.current_published_version_id = lesson_version.id; db.commit()
    return workspace, course, course_version, section, lesson, lesson_version, chunk, document, version


def _seed_set(db: Session, workspace, course, course_version, lesson, lesson_version, chunk, document, version):
    practice_set = PracticeSet(workspace_id=workspace.id, course_id=course.id, course_version_id=course_version.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, output_language="zh-CN", difficulty="standard", item_count=2, generation_config={}, lifecycle_status="active")
    db.add(practice_set); db.flush()
    single = PracticeItem(practice_set_id=practice_set.id, workspace_id=workspace.id, ordinal=0, item_type="single_choice", stem="Which halves the interval?", options=[{"option_key": "a", "text": "Binary search"}, {"option_key": "b", "text": "Linear scan"}], answer_spec={"correct_option_key": "a", "option_rationales": {"a": {"rationale": "halves", "citation_ids": ["e1"]}, "b": {"rationale": "scans all", "citation_ids": ["e1"]}}, "citation_ids": ["e1"]})
    short = PracticeItem(practice_set_id=practice_set.id, workspace_id=workspace.id, ordinal=1, item_type="short_answer", stem="Explain halving.", options=None, answer_spec={"reference_answer": "It halves the interval.", "rubric": [{"criterion_key": "c1", "description": "names halving", "weight": 100, "citation_ids": ["e1"]}], "citation_ids": ["e1"]})
    db.add_all([single, short]); db.flush()
    for item in (single, short):
        db.add(PracticeItemCitation(practice_item_id=item.id, workspace_id=workspace.id, citation_key="e1", document_id=document.id, document_version_id=version.id, document_chunk_id=chunk.id))
    db.commit()
    return practice_set, single, short


def _set_url(workspace, course, version, lesson, lesson_version) -> str:
    return f"/api/v1/workspaces/{workspace.id}/courses/{course.id}/versions/{version.id}/lessons/{lesson.id}/versions/{lesson_version.id}/practice-sets"


TEST_WORKER_ID = "test-worker"


def _run_as_worker(db: Session, job: PracticeJob, fn) -> None:
    """Drive a practice job the way the worker does, but on the test session.

    Establishes a real owner + lease so the production owner/lease checks inside
    execute_generation/execute_grading are exercised, not bypassed.
    """
    job.status = "running"; job.attempt_count = max(1, job.attempt_count + 1)
    job.worker_id = TEST_WORKER_ID; job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)
    db.commit()
    try:
        fn(db, get_settings(), job, worker_id=TEST_WORKER_ID, lease_lost=None)
        db.commit()
    except ValueError:
        db.rollback()
        raise


def test_pre_submission_item_read_hides_grading_material(client: TestClient, db_session: Session) -> None:
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    practice_set, single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    detail = client.get(f"/api/v1/workspaces/{workspace.id}/practice-sets/{practice_set.id}").json()
    leaked = _collect_keys(detail) & PRACTICE_FORBIDDEN
    assert not leaked, f"hidden grading material leaked: {leaked}"
    item = next(i for i in detail["items"] if i["id"] == single.id)
    assert {o["option_key"] for o in item["options"]} == {"a", "b"}
    assert all("is_correct" not in o for o in item["options"])


def test_single_choice_is_graded_deterministically_without_provider(client: TestClient, db_session: Session, monkeypatch) -> None:
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    _practice_set, single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    calls = []
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: calls.append(1) or ({}, {}))
    correct = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "att-correct"}, json={"external_processing_ack": False, "option_key": "a"})
    assert correct.status_code == 200
    body = correct.json()
    assert body["status"] == "succeeded" and body["feedback"]["verdict"] == "correct" and body["feedback"]["score"] == 100
    assert calls == []
    wrong = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "att-wrong"}, json={"external_processing_ack": False, "option_key": "b"})
    assert wrong.json()["feedback"]["verdict"] == "incorrect" and wrong.json()["feedback"]["score"] == 0
    invalid = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "att-bad"}, json={"external_processing_ack": False, "option_key": "zzz"})
    assert invalid.status_code == 422


def test_attempt_idempotency_and_conflict(client: TestClient, db_session: Session) -> None:
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    _set, single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    first = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "k1"}, json={"external_processing_ack": False, "option_key": "a"})
    replay = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "k1"}, json={"external_processing_ack": False, "option_key": "a"})
    assert replay.json()["id"] == first.json()["id"]
    conflict = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "k1"}, json={"external_processing_ack": False, "option_key": "b"})
    assert conflict.status_code == 409


def test_short_answer_grading_ungradable_never_fixed_score(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    _set, _single, short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    attempt = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{short.id}/attempts", headers={"Idempotency-Key": "s1"}, json={"external_processing_ack": True, "text": "I do not know."}).json()
    job = db_session.query(PracticeJob).filter_by(practice_attempt_id=attempt["id"]).one()
    results = iter([({"verdict": "ungradable", "score": None, "criterion_results": [{"criterion_key": "c1", "met": "none", "note": "not addressed"}], "blocks": [{"block_key": "b1", "type": "limitation", "text": "cannot judge", "citation_ids": []}]}, {"input_tokens": 5, "output_tokens": 5})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(results))
    _run_as_worker(db_session, job, execute_grading)
    graded = client.get(f"/api/v1/workspaces/{workspace.id}/practice-attempts/{attempt['id']}").json()
    assert graded["status"] == "succeeded"
    assert graded["feedback"]["verdict"] == "ungradable" and graded["feedback"]["score"] is None
    assert graded["feedback"]["is_ai_graded"] is True
    leaked = _collect_keys(graded) & PRACTICE_FORBIDDEN
    assert not leaked


def test_short_answer_repair_failure_leaves_no_feedback(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    _set, _single, short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    attempt = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{short.id}/attempts", headers={"Idempotency-Key": "s2"}, json={"external_processing_ack": True, "text": "some answer"}).json()
    job = db_session.query(PracticeJob).filter_by(practice_attempt_id=attempt["id"]).one()
    bad = {"verdict": "correct", "score": 100, "criterion_results": [{"criterion_key": "missing", "met": "full", "note": "x"}], "blocks": [{"block_key": "b1", "type": "explanation", "text": "ok", "citation_ids": ["zzz"]}]}
    results = iter([(bad, {"input_tokens": 1, "output_tokens": 1}), (bad, {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(results))
    try:
        _run_as_worker(db_session, job, execute_grading)
    except ValueError:
        db_session.get(PracticeJob, job.id).status = "failed"; db_session.commit()
    graded = client.get(f"/api/v1/workspaces/{workspace.id}/practice-attempts/{attempt['id']}").json()
    assert graded["feedback"] is None
    assert db_session.query(PracticeFeedback).filter_by(practice_attempt_id=attempt["id"]).count() == 0


def test_generation_success_and_workspace_isolation(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    workspace_other = Workspace(name="Other", slug="other"); db_session.add(workspace_other); db_session.flush(); db_session.commit()
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=document.id, document_version_id=docver.id, chunk_id=chunk.id, document_name=document.display_name, heading_path=[], start_offset=0, end_offset=len(chunk.content)))]))
    artifact = {"items": [
        {"item_key": "q1", "item_type": "single_choice", "stem": "pick", "citation_ids": ["e1"], "options": [{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["e1"]}, {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["e1"]}]},
        {"item_key": "q2", "item_type": "short_answer", "stem": "explain", "citation_ids": ["e1"], "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100, "citation_ids": ["e1"]}], "reference_answer": "ref"},
    ]}
    provider = iter([({"queries": ["q"]}, {"input_tokens": 2, "output_tokens": 2}), (artifact, {"input_tokens": 10, "output_tokens": 20})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(provider))
    created = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "gen-1"}, json={"item_count": 2, "difficulty": "standard", "external_processing_ack": True})
    job = db_session.get(PracticeJob, created.json()["id"])
    _run_as_worker(db_session, job, execute_generation)
    sets = client.get(_set_url(workspace, course, version, lesson, lesson_version)).json()
    assert len(sets) == 1 and sets[0]["item_count"] == 2
    assert client.get(f"/api/v1/workspaces/{workspace_other.id}/practice-sets/{sets[0]['id']}").status_code == 404


def test_generation_rejects_insufficient_evidence(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, _chunk, _document, _docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", []))
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: ({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}))
    created = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "gen-noev"}, json={"item_count": 1, "external_processing_ack": True})
    job = db_session.get(PracticeJob, created.json()["id"])
    try:
        _run_as_worker(db_session, job, execute_generation)
    except ValueError:
        pass
    db_session.get(PracticeJob, job.id).status = "failed"
    db_session.get(PracticeJob, job.id).error_code = "insufficient_evidence"; db_session.commit()
    assert client.get(_set_url(workspace, course, version, lesson, lesson_version)).json() == []


def test_generation_idempotency_conflict(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, _chunk, _document, _docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    url = _set_url(workspace, course, version, lesson, lesson_version)
    first = client.post(url, headers={"Idempotency-Key": "dup"}, json={"item_count": 2, "difficulty": "standard", "external_processing_ack": True})
    replay = client.post(url, headers={"Idempotency-Key": "dup"}, json={"item_count": 2, "difficulty": "standard", "external_processing_ack": True})
    assert replay.json()["id"] == first.json()["id"]
    conflict = client.post(url, headers={"Idempotency-Key": "dup"}, json={"item_count": 5, "difficulty": "standard", "external_processing_ack": True})
    assert conflict.status_code == 409


def test_generation_requires_ack_and_inactive_version(client: TestClient, db_session: Session) -> None:
    workspace, course, version, _section, lesson, lesson_version, _chunk, _document, _docver = _reader_fixture(db_session)
    url = _set_url(workspace, course, version, lesson, lesson_version)
    assert client.post(url, headers={"Idempotency-Key": "noack"}, json={"item_count": 2, "external_processing_ack": False}).status_code == 422
    assert client.post(url, headers={"Idempotency-Key": "toomany"}, json={"item_count": 11, "external_processing_ack": True}).status_code == 422
    course.current_active_version_id = None; db_session.commit()
    assert client.post(url, headers={"Idempotency-Key": "inactive"}, json={"item_count": 2, "external_processing_ack": True}).status_code == 409


def test_cancelled_generation_does_not_commit_set(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: ("t", [RetrievalResult(score=0.9, text=chunk.content, citation=CitationRead(document_id=document.id, document_version_id=docver.id, chunk_id=chunk.id, document_name=document.display_name, heading_path=[], start_offset=0, end_offset=len(chunk.content)))]))
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: ({"queries": ["q"]}, {"input_tokens": 1, "output_tokens": 1}))
    created = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "gen-cancel"}, json={"item_count": 1, "external_processing_ack": True})
    job = db_session.get(PracticeJob, created.json()["id"])
    job.status = "cancel_requested"; job.attempt_count = 1; job.worker_id = TEST_WORKER_ID; job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=300); db_session.commit()
    try:
        execute_generation(db_session, get_settings(), job, worker_id=TEST_WORKER_ID, lease_lost=None)
        raise AssertionError("expected cancel to abort generation")
    except ValueError as exc:
        assert str(exc) == "practice_canceled"
    db_session.rollback()
    assert client.get(_set_url(workspace, course, version, lesson, lesson_version)).json() == []


def test_delete_attempt_and_set_remove_answers_and_feedback(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    monkeypatch.setattr(practice, "enqueue_practice_set_deletion", lambda *_a: None)
    practice_set, single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    attempt = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "del-1"}, json={"external_processing_ack": False, "option_key": "a"}).json()
    assert client.delete(f"/api/v1/workspaces/{workspace.id}/practice-attempts/{attempt['id']}").status_code == 202
    assert client.get(f"/api/v1/workspaces/{workspace.id}/practice-attempts/{attempt['id']}").status_code == 404
    assert db_session.query(PracticeFeedback).filter_by(practice_attempt_id=attempt["id"]).count() == 0
    assert client.delete(f"/api/v1/workspaces/{workspace.id}/practice-sets/{practice_set.id}").status_code == 202
    from learn_platform_api.services.practice import cleanup_set
    cleanup_set(db_session, practice_set.id)
    assert client.get(f"/api/v1/workspaces/{workspace.id}/practice-sets/{practice_set.id}").status_code == 404
    assert db_session.query(PracticeItem).filter_by(practice_set_id=practice_set.id).count() == 0


def test_course_deletion_cleans_practice(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_set_deletion", lambda *_a: None)
    practice_set, _single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    client.delete(f"/api/v1/workspaces/{workspace.id}/courses/{course.id}")
    assert db_session.get(PracticeSet, practice_set.id).lifecycle_status == "deleting"


def test_source_degraded_blocks_new_generation_and_keeps_history(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    practice_set, _single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    document.lifecycle_status = "deleted"; db_session.commit()
    detail = client.get(f"/api/v1/workspaces/{workspace.id}/practice-sets/{practice_set.id}").json()
    assert detail["source_degraded"] is True
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    resp = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "deg"}, json={"item_count": 1, "external_processing_ack": True})
    assert resp.status_code == 409 and resp.json()["detail"] == "source_snapshot_stale"


def test_agent_run_identity_recognizes_practice(client: TestClient, db_session: Session) -> None:
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    practice_set, _single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    job = PracticeJob(workspace_id=workspace.id, job_type="generate_set", practice_set_id=practice_set.id, course_id=course.id, course_version_id=version.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, output_language="zh-CN", difficulty="standard", item_count=2, request_hash="0" * 64, status="succeeded", idempotency_key="j", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    db_session.add(job); db_session.flush()
    db_session.add(AgentRun(practice_job_id=job.id, workspace_id=workspace.id, role="exercise_author", attempt_number=1, status="succeeded"))
    db_session.commit()
    runs = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"course_id": course.id}).json()
    assert any(r["role"] == "exercise_author" for r in runs)
    detail = next(r for r in runs if r["role"] == "exercise_author")
    assert detail["identity"]["kind"] == "practice"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["lesson_title"] == "Binary search"


def test_generation_idempotency_race_converts_integrity_error(client: TestClient, db_session: Session, monkeypatch) -> None:
    """A concurrent insert that wins the (workspace, key) race must be converted
    to normal idempotent behavior, never leaked as a DB exception."""
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, _chunk, _document, _docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    # Seed an already-completed (non-active) job that the existence probe will
    # "miss" so the new insert collides on the unique key.
    request_hash = practice._hash(f"{version.id}|{lesson_version.id}|2|standard|zh-CN")
    seeded = PracticeJob(workspace_id=workspace.id, job_type="generate_set", course_id=course.id, course_version_id=version.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, output_language="zh-CN", difficulty="standard", item_count=2, request_hash=request_hash, status="succeeded", idempotency_key="race", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    db_session.add(seeded); db_session.flush()
    db_session.add(PracticeJobSource(practice_job_id=seeded.id, workspace_id=workspace.id, document_id=_document.id, document_version_id=_docver.id)); db_session.commit()
    monkeypatch.setattr(practice, "_existing_idempotent_job", lambda *_a: None)
    replay = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "race"}, json={"item_count": 2, "difficulty": "standard", "output_language": "zh-CN", "external_processing_ack": True})
    assert replay.status_code == 202
    assert replay.json()["id"] == seeded.id


def test_generation_idempotency_race_conflict_converted(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    workspace, course, version, _section, lesson, lesson_version, _chunk, _document, _docver = _reader_fixture(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    seeded_hash = practice._hash(f"{version.id}|{lesson_version.id}|2|standard|zh-CN")
    seeded = PracticeJob(workspace_id=workspace.id, job_type="generate_set", course_id=course.id, course_version_id=version.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, output_language="zh-CN", difficulty="standard", item_count=2, request_hash=seeded_hash, status="succeeded", idempotency_key="race2", attempt_count=1, external_processing_ack_at=datetime.now(timezone.utc))
    db_session.add(seeded); db_session.flush()
    db_session.add(PracticeJobSource(practice_job_id=seeded.id, workspace_id=workspace.id, document_id=_document.id, document_version_id=_docver.id)); db_session.commit()
    monkeypatch.setattr(practice, "_existing_idempotent_job", lambda *_a: None)
    conflict = client.post(_set_url(workspace, course, version, lesson, lesson_version), headers={"Idempotency-Key": "race2"}, json={"item_count": 5, "difficulty": "standard", "output_language": "zh-CN", "external_processing_ack": True})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "idempotency_key_conflict"


def test_source_degraded_keeps_history_but_blocks_all_new_attempts(client: TestClient, db_session: Session) -> None:
    """source_degraded is fully read-only: history visible, but new single-choice
    AND short-answer attempts both return source_snapshot_stale."""
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    practice_set, single, short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    document.lifecycle_status = "deleted"; db_session.commit()
    detail = client.get(f"/api/v1/workspaces/{workspace.id}/practice-sets/{practice_set.id}").json()
    assert detail["source_degraded"] is True and len(detail["items"]) == 2
    single_resp = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts", headers={"Idempotency-Key": "deg-single"}, json={"external_processing_ack": False, "option_key": "a"})
    assert single_resp.status_code == 409 and single_resp.json()["detail"] == "source_snapshot_stale"
    short_resp = client.post(f"/api/v1/workspaces/{workspace.id}/practice-items/{short.id}/attempts", headers={"Idempotency-Key": "deg-short"}, json={"external_processing_ack": True, "text": "answer"})
    assert short_resp.status_code == 409 and short_resp.json()["detail"] == "source_snapshot_stale"
    # Attempt was NOT created.
    assert client.get(f"/api/v1/workspaces/{workspace.id}/practice-items/{single.id}/attempts").json() == []


def test_deleting_set_reconciler_re_enqueues_and_cleans_up(db_session: Session, monkeypatch) -> None:
    """A deleting set whose cleanup enqueue failed must be retried by the
    reconciler once it goes stale, then fully cleaned with no residue."""
    from learn_platform_api.services import practice, jobs as jobs_service
    from datetime import timedelta
    workspace, course, version, _section, lesson, lesson_version, chunk, document, docver = _reader_fixture(db_session)
    practice_set, _single, _short = _seed_set(db_session, workspace, course, version, lesson, lesson_version, chunk, document, docver)
    monkeypatch.setattr(practice, "enqueue_practice_set_deletion", lambda *_a: None)
    practice.delete_set(db_session, get_settings(), workspace.id, practice_set.id)
    assert db_session.get(PracticeSet, practice_set.id).lifecycle_status == "deleting"
    # Simulate stale: set deleted_at well in the past.
    stale = db_session.get(PracticeSet, practice_set.id)
    stale.deleted_at = datetime.now(timezone.utc) - timedelta(hours=1); db_session.commit()
    enqueued = []
    monkeypatch.setattr(jobs_service, "enqueue_practice_set_deletion", lambda _s, sid: enqueued.append(sid))
    recovered = jobs_service.reconcile_jobs(db_session, get_settings())
    assert recovered >= 1
    assert practice_set.id in enqueued
    # Now actually clean up (as the worker would).
    from learn_platform_api.services.practice import cleanup_set
    cleanup_set(db_session, practice_set.id)
    for model in [PracticeSet, PracticeItem, PracticeItemCitation, PracticeAttempt, PracticeFeedback, PracticeJob, PracticeJobSource]:
        assert db_session.query(model).filter_by(workspace_id=workspace.id).count() == 0, f"{model.__name__} residue"

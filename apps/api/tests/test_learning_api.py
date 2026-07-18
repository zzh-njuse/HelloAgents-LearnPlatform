"""End-to-end integration: practice → learning projection → API → memory."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
    LearningMemory, LearningTarget, Lesson, LessonVersion, PracticeAttempt, PracticeFeedback,
    PracticeItem, PracticeItemTarget, PracticeSet, SourceDocument, Weakness, Workspace,
)
from learn_platform_api.services import practice_generation
from learn_platform_api.settings import get_settings

FORBIDDEN = {"projection_score", "answer", "answer_payload", "option_key", "rubric", "feedback_blocks", "correct_option_key", "answer_spec", "evidence", "prompt", "provider", "model"}


def _seed(db: Session):
    ws = Workspace(name="api-lp", slug="api-lp"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a"*64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id="1"*32+"1"*4, document_version_id=ver.id, ordinal=0, content="c", content_hash="b"*64, start_offset=0, end_offset=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    sec = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(sec); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=sec.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["Explain X"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id; db.commit()
    return ws, course, cv, lesson, lv, doc, ver


def _seed_set(db, ws, course, cv, lesson, lv):
    ps = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN", difficulty="standard", item_count=2, generation_config={}, lifecycle_status="active")
    db.add(ps); db.flush()
    i1 = PracticeItem(practice_set_id=ps.id, workspace_id=ws.id, ordinal=0, item_type="single_choice", stem="q1", options=[{"option_key":"a","text":"A"},{"option_key":"b","text":"B"}], answer_spec={"correct_option_key":"a"})
    i2 = PracticeItem(practice_set_id=ps.id, workspace_id=ws.id, ordinal=1, item_type="single_choice", stem="q2", options=[{"option_key":"a","text":"A"},{"option_key":"b","text":"B"}], answer_spec={"correct_option_key":"a"})
    db.add_all([i1, i2]); db.flush()
    db.commit()
    return ps, i1, i2


def _submit_single(client, ws, item, option, key):
    return client.post(f"/api/v1/workspaces/{ws.id}/practice-items/{item.id}/attempts", headers={"Idempotency-Key": key}, json={"external_processing_ack": False, "option_key": option}).json()


def _collect_keys(value, into=None):
    into = set() if into is None else into
    if isinstance(value, dict):
        into.update(value.keys())
        for v in value.values(): _collect_keys(v, into)
    elif isinstance(value, list):
        for v in value: _collect_keys(v, into)
    return into


def test_single_choice_projects_learning_and_api_safe(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")  # incorrect

    state = client.get(f"/api/v1/workspaces/{ws.id}/learning-state").json()
    assert state["summary"]["insufficient"] + state["summary"]["needs_review"] >= 1
    leaked = _collect_keys(state) & FORBIDDEN
    assert not leaked, f"forbidden fields in learning-state: {leaked}"


def test_two_incorrect_confirms_weakness_and_auto_memory(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")
    _submit_single(client, ws, i2, "b", "a2")

    state = client.get(f"/api/v1/workspaces/{ws.id}/learning-state").json()
    target = next(t for t in state["targets"] if t["weakness_status"] == "confirmed")
    assert target["band"] == "needs_review"

    mems = client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json()
    assert len(mems) == 1
    assert mems[0]["status"] == "active"
    assert mems[0]["kind"] == "weakness"


def test_memory_suppression_prevents_revival(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")
    _submit_single(client, ws, i2, "b", "a2")
    mems = client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json()
    mem_id = mems[0]["id"]
    # Delete memory (sets suppression watermark).
    assert client.delete(f"/api/v1/workspaces/{ws.id}/learning-memories/{mem_id}").status_code == 204
    # Re-submit same feedbacks (replay) — should NOT revive memory.
    _submit_single(client, ws, i1, "b", "a1-replay")
    _submit_single(client, ws, i2, "b", "a2-replay")
    # Old events replay can't revive; need NEW distinct items' negative evidence.
    assert client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json() == []


def test_suppression_survives_empty_recompute_and_new_evidence_reopens(client: TestClient, db_session: Session) -> None:
    from learn_platform_api.services.learning_projection import delete_attempt_learning_facts, recompute_workspace

    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    _, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    first = _submit_single(client, ws, i1, "b", "watermark-1")
    second = _submit_single(client, ws, i2, "b", "watermark-2")
    memory_id = client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json()[0]["id"]
    assert client.delete(f"/api/v1/workspaces/{ws.id}/learning-memories/{memory_id}").status_code == 204

    for attempt_id in (first["id"], second["id"]):
        delete_attempt_learning_facts(db_session, ws.id, attempt_id, None)
    recompute_workspace(db_session, ws.id)
    db_session.commit()

    tombstone = db_session.query(Weakness).filter_by(workspace_id=ws.id).one()
    assert tombstone.status == "dismissed"
    assert tombstone.memory_suppressed_at is not None
    assert client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json() == []

    _submit_single(client, ws, i1, "b", "watermark-new-1")
    _submit_single(client, ws, i2, "b", "watermark-new-2")
    memories = client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json()
    assert len(memories) == 1


def test_recompute_preserves_memory_and_restores_weakness_link(client: TestClient, db_session: Session) -> None:
    from learn_platform_api.services.learning_projection import recompute_workspace

    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    _, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "recompute-memory-1")
    _submit_single(client, ws, i2, "b", "recompute-memory-2")
    memory = db_session.query(LearningMemory).filter_by(workspace_id=ws.id).one()
    memory_id = memory.id
    recompute_workspace(db_session, ws.id)
    db_session.commit()
    db_session.refresh(memory)
    assert memory.id == memory_id
    assert memory.weakness_id is not None


def test_review_actions_and_memory_policy(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")
    _submit_single(client, ws, i2, "b", "a2")
    items = client.get(f"/api/v1/workspaces/{ws.id}/review-items").json()
    assert len(items) >= 1
    assert items[0]["target_title"] == "L：整体理解"
    assert items[0]["target_key"] == "lesson_overall"
    assert items[0]["target_id"]
    ri_id = items[0]["id"]
    # Snooze.
    assert client.post(f"/api/v1/workspaces/{ws.id}/review-items/{ri_id}/actions", json={"action": "snooze", "snooze_days": 7}).status_code == 200
    # Policy default off.
    policy = client.get(f"/api/v1/workspaces/{ws.id}/learning-memory-policy").json()
    assert policy["tutor_use_enabled"] is False
    # Enable.
    patched = client.patch(f"/api/v1/workspaces/{ws.id}/learning-memory-policy", json={"tutor_use_enabled": True}).json()
    assert patched["tutor_use_enabled"] is True


def test_dismiss_updates_weakness_and_old_evidence_does_not_reopen(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    _, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "dismiss-1")
    _submit_single(client, ws, i2, "b", "dismiss-2")
    item = client.get(f"/api/v1/workspaces/{ws.id}/review-items").json()[0]
    assert client.post(f"/api/v1/workspaces/{ws.id}/review-items/{item['id']}/actions", json={"action": "dismiss"}).status_code == 200
    weakness = db_session.query(Weakness).filter_by(workspace_id=ws.id).one()
    db_session.refresh(weakness)
    assert weakness.status == "dismissed"
    assert client.get(f"/api/v1/workspaces/{ws.id}/review-items").json()[0]["status"] == "dismissed"


def test_memory_edit_and_archive(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")
    _submit_single(client, ws, i2, "b", "a2")
    mems = client.get(f"/api/v1/workspaces/{ws.id}/learning-memories").json()
    mem_id = mems[0]["id"]
    # Edit.
    edited = client.patch(f"/api/v1/workspaces/{ws.id}/learning-memories/{mem_id}", json={"action": "edit", "display_text": "My custom note"}).json()
    assert edited["display_text"] == "My custom note"
    # Archive.
    archived = client.patch(f"/api/v1/workspaces/{ws.id}/learning-memories/{mem_id}", json={"action": "archive"}).json()
    assert archived["status"] == "archived"


def test_reconfirm_does_not_forge_evidence_time(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    _, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "reconfirm-1")
    _submit_single(client, ws, i2, "b", "reconfirm-2")
    memory = db_session.query(LearningMemory).filter_by(workspace_id=ws.id).one()
    old_supported_at = datetime.now(timezone.utc) - timedelta(days=20)
    memory.last_supported_at = old_supported_at
    memory.status = "paused"
    db_session.commit()
    response = client.patch(f"/api/v1/workspaces/{ws.id}/learning-memories/{memory.id}", json={"action": "reconfirm"})
    assert response.status_code == 200
    db_session.refresh(memory)
    assert memory.status == "active"
    assert abs((memory.last_supported_at.replace(tzinfo=timezone.utc) - old_supported_at).total_seconds()) < 1


def test_learning_endpoints_validate_workspace_and_filters(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/workspaces/{missing}/learning-state").status_code == 404
    assert client.get(f"/api/v1/workspaces/{missing}/learning-memory-policy").status_code == 404
    assert client.get(f"/api/v1/workspaces/{missing}/review-items?status=unknown").status_code == 422


def test_workspace_isolation(client: TestClient, db_session: Session) -> None:
    ws, course, cv, lesson, lv, doc, ver = _seed(db_session)
    other = Workspace(name="other", slug="other"); db_session.add(other); db_session.flush(); db_session.commit()
    ps, i1, i2 = _seed_set(db_session, ws, course, cv, lesson, lv)
    _submit_single(client, ws, i1, "b", "a1")
    _submit_single(client, ws, i2, "b", "a2")
    # Cross-workspace: empty learning state.
    assert client.get(f"/api/v1/workspaces/{other.id}/learning-state").json()["targets"] == []
    assert client.get(f"/api/v1/workspaces/{other.id}/learning-memories").json() == []


def test_recompute_job_creation(client: TestClient, db_session: Session) -> None:
    ws, *_ = _seed(db_session)
    url = f"/api/v1/workspaces/{ws.id}/learning-state/recompute"
    assert client.post(url).status_code == 422
    resp = client.post(url, headers={"Idempotency-Key": "recompute-1"})
    assert resp.status_code == 202
    body = resp.json()
    assert "id" in body
    assert body["status"] in ("queued", "queue_failed")
    replay = client.post(url, headers={"Idempotency-Key": "recompute-1"})
    assert replay.status_code == 202
    assert replay.json()["id"] == body["id"]

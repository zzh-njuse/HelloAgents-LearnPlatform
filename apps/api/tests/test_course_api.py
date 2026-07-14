from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Course, CourseGenerationJob, CourseGenerationJobSource, CourseSection, CourseVersion, DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument, Workspace
from learn_platform_api.services.course_generation import execute_generation
from learn_platform_api.settings import get_settings
from academic_companion.course_agents import CourseOutlineArtifact, LessonDraftArtifact, validate_citations


def _workspace(client: TestClient) -> str:
    return client.post("/api/v1/workspaces", json={"name": "Course workspace"}).json()["id"]


def _ready_document(db: Session, workspace_id: str) -> str:
    document = SourceDocument(workspace_id=workspace_id, display_name="ready.md")
    db.add(document)
    db.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="ready.md", mime_type="text/markdown", byte_size=1, sha256="0" * 64, original_storage_uri="test")
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.commit()
    return document.id


def test_create_course_snapshots_ready_sources(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import courses

    queued: list[str] = []
    monkeypatch.setattr(courses, "enqueue_course_generation_job", lambda _settings, job_id: queued.append(job_id))
    workspace_id = _workspace(client)
    document_id = _ready_document(db_session, workspace_id)

    response = client.post(f"/api/v1/workspaces/{workspace_id}/courses", headers={"Idempotency-Key": "course-create-1"}, json={"title": "Course", "goal": "Learn", "document_ids": [document_id], "external_processing_ack": True})

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["status"] == "queued"
    assert len(body["source_document_version_ids"]) == 1
    assert queued == [body["job"]["id"]]
    assert client.get(f"/api/v1/workspaces/{workspace_id}/courses").json()[0]["id"] == body["course"]["id"]
    replay = client.post(f"/api/v1/workspaces/{workspace_id}/courses", headers={"Idempotency-Key": "course-create-1"}, json={"title": "Course", "goal": "Learn", "document_ids": [document_id], "external_processing_ack": True})
    assert replay.status_code == 202
    assert replay.json()["course"]["id"] == body["course"]["id"]
    assert replay.json()["job"]["id"] == body["job"]["id"]
    assert queued == [body["job"]["id"]]


def test_course_endpoints_are_workspace_isolated(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import courses

    monkeypatch.setattr(courses, "enqueue_course_generation_job", lambda *_args: None)
    workspace_a = _workspace(client)
    workspace_b = _workspace(client)
    document_id = _ready_document(db_session, workspace_a)
    created = client.post(f"/api/v1/workspaces/{workspace_a}/courses", headers={"Idempotency-Key": "workspace-isolation"}, json={"title": "Private course", "goal": "Learn", "document_ids": [document_id], "external_processing_ack": True}).json()

    assert client.get(f"/api/v1/workspaces/{workspace_b}/courses/{created['course']['id']}").status_code == 404
    assert client.get(f"/api/v1/workspaces/{workspace_b}/course-generation-jobs/{created['job']['id']}").status_code == 404
    assert client.get(f"/api/v1/workspaces/{workspace_b}/courses").json() == []


def test_create_course_requires_ack_and_ready_sources(client: TestClient, db_session: Session) -> None:
    workspace_id = _workspace(client)
    document_id = _ready_document(db_session, workspace_id)
    missing_ack = client.post(f"/api/v1/workspaces/{workspace_id}/courses", headers={"Idempotency-Key": "course-create-2"}, json={"title": "Course", "goal": "Learn", "document_ids": [document_id], "external_processing_ack": False})
    invalid_source = client.post(f"/api/v1/workspaces/{workspace_id}/courses", headers={"Idempotency-Key": "course-create-3"}, json={"title": "Course", "goal": "Learn", "document_ids": ["missing"], "external_processing_ack": True})
    assert missing_ack.status_code == 422
    assert invalid_source.status_code == 422


def test_fake_architect_to_reader_vertical_path(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import course_generation

    workspace_id = _workspace(client)
    document_id = _ready_document(db_session, workspace_id)
    document = db_session.get(SourceDocument, document_id)
    chunk = DocumentChunk(id="77777777-7777-7777-7777-777777777777", document_version_id=document.current_version_id, ordinal=0, content="Retrieval narrows a large candidate set.", content_hash="7" * 64, start_offset=0, end_offset=40)
    course = Course(workspace_id=workspace_id, title="Search", goal="Understand retrieval")
    db_session.add_all([chunk, course]); db_session.flush()
    job = CourseGenerationJob(workspace_id=workspace_id, course_id=course.id, job_type="course_outline", status="running", idempotency_key="vertical-outline", attempt_count=1)
    db_session.add(job); db_session.flush()
    db_session.add(CourseGenerationJobSource(course_generation_job_id=job.id, workspace_id=workspace_id, document_id=document.id, document_version_id=document.current_version_id))
    db_session.commit()
    monkeypatch.setattr(course_generation, "evidence_search", lambda *_args, **_kwargs: ([{"citation_id": "e1", "text": chunk.content}], {"e1": chunk}))
    provider_results = iter([
        ({"queries": ["retrieval narrowing"]}, {"input_tokens": 2, "output_tokens": 2}),
        ({"title": "Search", "summary": "Course", "sections": [{"title": "Retrieval", "objective": "Learn retrieval", "citation_ids": ["e1"], "lessons": [{"title": "Why retrieval", "objective": "Explain narrowing", "citation_ids": ["e1"]}]}]}, {"input_tokens": 10, "output_tokens": 20}),
    ])
    monkeypatch.setattr(course_generation, "call_provider", lambda *_args: next(provider_results))

    execute_generation(db_session, get_settings(), job)
    db_session.commit()

    db_session.refresh(job)
    version = db_session.get(CourseVersion, job.course_version_id)
    lesson = db_session.query(Lesson).filter_by(course_version_id=version.id).one()
    lesson_job = CourseGenerationJob(workspace_id=workspace_id, course_id=course.id, course_version_id=version.id, lesson_id=lesson.id, job_type="lesson_draft", status="running", idempotency_key="vertical-lesson", attempt_count=1)
    db_session.add(lesson_job); db_session.flush()
    db_session.add(CourseGenerationJobSource(course_generation_job_id=lesson_job.id, workspace_id=workspace_id, document_id=document.id, document_version_id=document.current_version_id)); db_session.commit()
    lesson_provider_results = iter([
        ({"queries": ["why retrieval"]}, {"input_tokens": 2, "output_tokens": 2}),
        ({"title": "Why retrieval", "learning_objectives": ["Explain narrowing"], "blocks": [{"block_key": "p1", "type": "paragraph", "text": "Retrieval narrows candidates.", "citation_ids": ["e1"]}]}, {"input_tokens": 10, "output_tokens": 20}),
    ])
    monkeypatch.setattr(course_generation, "call_provider", lambda *_args: next(lesson_provider_results))
    execute_generation(db_session, get_settings(), lesson_job); db_session.commit()
    lesson_version = db_session.query(LessonVersion).filter_by(lesson_id=lesson.id).one()
    draft_detail = client.get(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}").json()
    draft = draft_detail["versions"][0]["sections"][0]["lessons"][0]["versions"][0]
    assert draft["status"] == "draft"
    assert draft["blocks"][0]["text"] == "Retrieval narrows candidates."
    assert draft["blocks"][0]["citation_ids"] == [draft["citations"][0]["citation_id"]]
    assert draft["citations"][0]["document_name"] == "ready.md"
    assert client.post(f"/api/v1/workspaces/{workspace_id}/lessons/{lesson.id}/versions/{lesson_version.id}/publish", json={"expected_current_published_version_id": None}).status_code == 200
    assert client.post(f"/api/v1/workspaces/{workspace_id}/lessons/{lesson.id}/versions/{lesson_version.id}/publish", json={"expected_current_published_version_id": None}).status_code == 409
    assert client.post(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}/versions/{version.id}/activate", json={"expected_current_active_version_id": None}).status_code == 200
    assert client.post(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}/versions/{version.id}/activate", json={"expected_current_active_version_id": None}).status_code == 409
    response = client.get(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}/reader")
    assert response.status_code == 200
    published = response.json()["version"]["sections"][0]["lessons"][0]["published_version"]
    assert published["status"] == "published"
    assert published["citations"] == [{
        "citation_id": published["citations"][0]["citation_id"],
        "block_key": "p1",
        "document_id": document.id,
        "document_version_id": document.current_version_id,
        "chunk_id": chunk.id,
        "document_name": "ready.md",
        "heading_path": [],
        "start_offset": 0,
        "end_offset": 40,
        "available": True,
    }]
    summary = client.get(f"/api/v1/workspaces/{workspace_id}/courses").json()[0]
    assert summary["source_count"] == 1
    assert summary["published_lesson_count"] == 1
    assert summary["pending_lesson_count"] == 0
    assert summary["latest_job"]["id"] == lesson_job.id

    document.lifecycle_status = "deleted"
    db_session.commit()
    degraded = client.get(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}/reader").json()
    assert degraded["course"]["source_degraded"] is True
    assert degraded["version"]["sections"][0]["lessons"][0]["published_version"]["citations"][0]["available"] is False
    assert client.post(f"/api/v1/workspaces/{workspace_id}/courses/{course.id}/versions/{version.id}/activate", json={"expected_current_active_version_id": version.id}).status_code == 409


def test_course_artifacts_reject_budget_and_citation_violations() -> None:
    with pytest.raises(ValidationError):
        CourseOutlineArtifact.model_validate({"title": "Too large", "summary": "x", "sections": [{"title": str(index), "objective": "x", "citation_ids": ["e1"], "lessons": [{"title": "x", "objective": "x", "citation_ids": ["e1"]}]} for index in range(16)]})
    with pytest.raises(ValidationError):
        LessonDraftArtifact.model_validate({"title": "Lesson", "learning_objectives": ["x"], "blocks": [{"block_key": "same", "type": "paragraph", "text": "x", "citation_ids": ["e1"]}, {"block_key": "same", "type": "summary", "text": "x", "citation_ids": ["e1"]}]})
    artifact = LessonDraftArtifact.model_validate({"title": "Lesson", "learning_objectives": ["x"], "blocks": [{"block_key": "p1", "type": "paragraph", "text": "x", "citation_ids": ["e2"]}]})
    with pytest.raises(ValueError, match="unknown_citation"):
        validate_citations(artifact, {"e1"})

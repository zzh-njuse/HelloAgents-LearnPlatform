from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learn_platform_api.main import create_app
from learn_platform_api.db.models import DocumentChunk, DocumentVersion, IngestionJob, SourceDocument, Workspace, WorkspaceDeletionJob
from learn_platform_api.services.workspace_deletion import execute_deletion
from learn_platform_api.settings import get_settings


def test_health_and_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "learn-platform-api"}
    assert response.headers["X-Request-ID"] == "test-request"


def test_unhandled_error_is_logged_and_keeps_request_id() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/test-error")
    def test_error() -> None:
        raise RuntimeError("test failure")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-error", headers={"X-Request-ID": "failed-request"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "failed-request"
    assert response.json() == {"detail": "Internal Server Error"}


def test_system_info_is_redacted(client: TestClient) -> None:
    payload = client.get("/api/v1/system/info").json()

    assert payload["app_name"] == "HelloAgents Learn"
    assert "database_url" not in payload
    assert "qdrant_url" not in payload
    assert "redis_url" not in payload


def test_create_list_get_workspace(client: TestClient) -> None:
    created = client.post(
        "/api/v1/workspaces",
        json={"name": "算法复习", "description": "准备秋招"},
    )

    assert created.status_code == 201
    workspace = created.json()
    assert workspace["name"] == "算法复习"
    assert workspace["slug"] == "workspace"

    listed = client.get("/api/v1/workspaces").json()
    assert [item["id"] for item in listed] == [workspace["id"]]

    fetched = client.get(f"/api/v1/workspaces/{workspace['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == workspace


def test_slug_collision_gets_deterministic_suffix(client: TestClient) -> None:
    first = client.post("/api/v1/workspaces", json={"name": "Review Plan"})
    second = client.post("/api/v1/workspaces", json={"name": "Review Plan"})

    assert first.json()["slug"] == "review-plan"
    assert second.json()["slug"] == "review-plan-2"


def test_workspace_validation_and_missing_record(client: TestClient) -> None:
    invalid = client.post("/api/v1/workspaces", json={"name": "   "})
    missing = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000")

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Workspace 不存在"


def test_list_pagination_is_bounded(client: TestClient) -> None:
    response = client.get("/api/v1/workspaces?limit=201")

    assert response.status_code == 422


def test_workspace_deletion_requires_name_and_hides_workspace(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import workspace_deletion

    queued: list[str] = []
    monkeypatch.setattr(workspace_deletion, "enqueue_workspace_deletion_job", lambda _settings, job_id: queued.append(job_id))
    workspace = client.post("/api/v1/workspaces", json={"name": "Delete me"}).json()

    impact = client.get(f"/api/v1/workspaces/{workspace['id']}/deletion-impact")
    mismatch = client.post(
        f"/api/v1/workspaces/{workspace['id']}/deletion",
        headers={"Idempotency-Key": "delete-1"},
        json={"confirmation_name": "wrong"},
    )
    deleted = client.post(
        f"/api/v1/workspaces/{workspace['id']}/deletion",
        headers={"Idempotency-Key": "delete-1"},
        json={"confirmation_name": "Delete me"},
    )

    assert impact.json() == {"document_count": 0, "course_count": 0, "active_job_count": 0, "tutor_session_count": 0}
    assert mismatch.status_code == 422
    assert deleted.status_code == 202
    assert queued == [deleted.json()["id"]]
    assert client.get("/api/v1/workspaces").json() == []
    assert client.get(f"/api/v1/workspaces/{workspace['id']}").status_code == 404
    assert db_session.get(Workspace, workspace["id"]).lifecycle_status == "deleting"


def test_workspace_deletion_enqueue_failure_is_retryable(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import workspace_deletion

    def fail_enqueue(*_args) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(workspace_deletion, "enqueue_workspace_deletion_job", fail_enqueue)
    workspace = client.post("/api/v1/workspaces", json={"name": "Queue failure"}).json()
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/deletion",
        headers={"Idempotency-Key": "delete-queue-failure"},
        json={"confirmation_name": "Queue failure"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queue_failed"
    job = db_session.get(WorkspaceDeletionJob, response.json()["id"])
    assert job.error_code == "queue_unavailable"


def test_workspace_deletion_removes_database_storage_and_index_rows(client: TestClient, db_session: Session, monkeypatch, tmp_path) -> None:
    from learn_platform_api.services import workspace_deletion

    monkeypatch.setattr(workspace_deletion, "enqueue_workspace_deletion_job", lambda *_: None)
    removed_qdrant: list[str] = []
    removed_storage: list[str] = []
    monkeypatch.setattr(workspace_deletion, "_delete_qdrant", lambda _settings, workspace_id: removed_qdrant.append(workspace_id))
    monkeypatch.setattr(workspace_deletion, "remove_tree", lambda _root, uri: removed_storage.append(uri))
    workspace = client.post("/api/v1/workspaces", json={"name": "Populated"}).json()
    document = SourceDocument(workspace_id=workspace["id"], display_name="notes.md")
    db_session.add(document); db_session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="notes.md", mime_type="text/markdown", byte_size=4, sha256="0" * 64, original_storage_uri="stored")
    db_session.add(version); db_session.flush()
    document.current_version_id = version.id
    chunk = DocumentChunk(id="00000000-0000-0000-0000-000000000123", document_version_id=version.id, ordinal=0, content="text", content_hash="1" * 64, start_offset=0, end_offset=4)
    ingestion = IngestionJob(workspace_id=workspace["id"], document_version_id=version.id, job_type="ingest_document", status="failed", idempotency_key="ingest")
    db_session.add_all([chunk, ingestion]); db_session.commit()
    response = client.post(f"/api/v1/workspaces/{workspace['id']}/deletion", headers={"Idempotency-Key": "delete-populated"}, json={"confirmation_name": "Populated"})
    job = db_session.get(WorkspaceDeletionJob, response.json()["id"])

    execute_deletion(db_session, get_settings().model_copy(update={"storage_root": tmp_path}), job)
    db_session.commit()

    assert db_session.get(Workspace, workspace["id"]) is None
    assert db_session.get(SourceDocument, document.id) is None
    assert db_session.get(DocumentVersion, version.id) is None
    assert db_session.get(WorkspaceDeletionJob, job.id).status == "succeeded"
    assert removed_qdrant == [workspace["id"]]
    assert removed_storage == [f"workspaces/{workspace['id']}"]

from fastapi import APIRouter
from fastapi.testclient import TestClient

from learn_platform_api.main import create_app


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

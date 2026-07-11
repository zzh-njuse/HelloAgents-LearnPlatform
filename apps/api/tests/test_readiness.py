from fastapi.testclient import TestClient

from learn_platform_api.routers import health
from learn_platform_api.services import readiness


def test_ready_reports_all_checks_without_connection_details(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(health, "check_postgres", lambda _engine: {"ok": True, "detail": "可用"})
    monkeypatch.setattr(health, "check_qdrant", lambda _url, _timeout: {"ok": True, "detail": "可用"})
    monkeypatch.setattr(health, "check_redis", lambda _url, _timeout: {"ok": False, "detail": "不可用"})
    monkeypatch.setattr(health, "check_storage", lambda _path: {"ok": True, "detail": "可写"})

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert set(payload["checks"]) == {"postgres", "qdrant", "redis", "storage"}
    serialized = response.text.lower()
    assert "localhost" not in serialized
    assert "postgresql" not in serialized
    assert "redis://" not in serialized


def test_redis_readiness_reports_malformed_url_as_unavailable(monkeypatch) -> None:
    def raise_value_error(*_args, **_kwargs):
        raise ValueError("invalid Redis URL")

    monkeypatch.setattr(readiness.Redis, "from_url", raise_value_error)

    assert readiness.check_redis("not-a-redis-url", 0.1) == {
        "ok": False,
        "detail": "不可用",
    }

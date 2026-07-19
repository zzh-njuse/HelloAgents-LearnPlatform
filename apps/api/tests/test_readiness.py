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
    monkeypatch.setattr(health, "check_tutor_skill", lambda: {"ok": True, "detail": "可用"})

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert set(payload["checks"]) == {"postgres", "qdrant", "redis", "storage", "tutor_skill"}
    serialized = response.text.lower()
    assert "localhost" not in serialized
    assert "postgresql" not in serialized
    assert "redis://" not in serialized
    # The public label may say "Skill"; implementation details must remain private.
    for forbidden in ("skill.md", "sha256", "content_hash", "prompt"):
        assert forbidden not in serialized
    assert payload["checks"]["tutor_skill"] == {"ok": True, "detail": "可用"}


def test_tutor_skill_readiness_degrades_when_skill_unavailable(monkeypatch) -> None:
    from academic_companion.teaching_skills import SkillUnavailable

    def _raise(*_a, **_k):
        raise SkillUnavailable("skill_not_found")

    # readiness imports load_skill by name, so patch the readiness-module reference.
    monkeypatch.setattr(readiness, "load_skill", _raise)
    result = readiness.check_tutor_skill()
    assert result == {"ok": False, "detail": "教学 Skill 不可用"}


def test_tutor_skill_readiness_ok_when_loadable(monkeypatch) -> None:
    assert readiness.check_tutor_skill() == {"ok": True, "detail": "可用"}


def test_ready_is_degraded_when_skill_missing_and_leaks_nothing(client: TestClient, monkeypatch) -> None:
    # Missing file / tampered metadata / unparseable hash all surface as the
    # same stable, non-sensitive degraded detail (corr 002/3.5).
    monkeypatch.setattr(health, "check_postgres", lambda _engine: {"ok": True, "detail": "可用"})
    monkeypatch.setattr(health, "check_qdrant", lambda _url, _timeout: {"ok": True, "detail": "可用"})
    monkeypatch.setattr(health, "check_redis", lambda _url, _timeout: {"ok": True, "detail": "可用"})
    monkeypatch.setattr(health, "check_storage", lambda _path: {"ok": True, "detail": "可写"})
    monkeypatch.setattr(health, "check_tutor_skill", lambda: {"ok": False, "detail": "教学 Skill 不可用"})
    response = client.get("/ready")
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["tutor_skill"] == {"ok": False, "detail": "教学 Skill 不可用"}
    serialized = response.text.lower()
    # No path, hash or prompt body in the detail.
    for forbidden in (".md", "sha256", "a7d5", "prompt", "c:\\", "/home/"):
        assert forbidden not in serialized


def test_redis_readiness_reports_false_ping_as_unavailable(monkeypatch) -> None:
    class Client:
        def ping(self):
            return False

        def close(self):
            pass

    monkeypatch.setattr(readiness.Redis, "from_url", lambda *_args, **_kwargs: Client())

    assert readiness.check_redis("redis://example", 0.1) == {
        "ok": False,
        "detail": "不可用",
    }


def test_redis_readiness_reports_malformed_url_as_unavailable(monkeypatch) -> None:
    def raise_value_error(*_args, **_kwargs):
        raise ValueError("invalid Redis URL")

    monkeypatch.setattr(readiness.Redis, "from_url", raise_value_error)

    assert readiness.check_redis("not-a-redis-url", 0.1) == {
        "ok": False,
        "detail": "不可用",
    }

from fastapi import APIRouter

from learn_platform_api.db.session import engine
from learn_platform_api.services.readiness import (
    check_postgres,
    check_qdrant,
    check_redis,
    check_storage,
)
from learn_platform_api.settings import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "learn-platform-api"}


@router.get("/ready")
def ready() -> dict[str, object]:
    settings = get_settings()
    checks = {
        "postgres": check_postgres(engine),
        "qdrant": check_qdrant(
            settings.qdrant_url, settings.readiness_timeout_seconds
        ),
        "redis": check_redis(settings.redis_url, settings.readiness_timeout_seconds),
        "storage": check_storage(settings.storage_root),
    }
    is_ready = all(bool(check["ok"]) for check in checks.values())
    return {"status": "ready" if is_ready else "degraded", "checks": checks}

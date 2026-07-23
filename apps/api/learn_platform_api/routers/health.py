from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from learn_platform_api.db.session import engine, get_db
from learn_platform_api.services.readiness import (
    check_code_execution,
    check_postgres,
    check_qdrant,
    check_redis,
    check_science_tool,
    check_storage,
    check_tutor_skill,
)
from learn_platform_api.settings import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "learn-platform-api"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, object]:
    settings = get_settings()
    checks = {
        "postgres": check_postgres(engine),
        "qdrant": check_qdrant(
            settings.qdrant_url, settings.readiness_timeout_seconds
        ),
        "redis": check_redis(settings.redis_url, settings.readiness_timeout_seconds),
        "storage": check_storage(settings.storage_root),
        "tutor_skill": check_tutor_skill(),
        # Slice 4: optional MCP capabilities — unavailable does NOT degrade
        # overall API readiness (Spec 004 §10, ADR 006 §2.2).
        # Per correction 004 §3/§4: readiness from DB projection, not config.
        "code_execution": check_code_execution(settings, db=db),
        "science_tool": check_science_tool(settings, db=db),
    }
    # Core readiness: postgres + qdrant + redis + storage + tutor_skill
    # MCP capabilities are optional and don't affect overall status.
    core_keys = {"postgres", "qdrant", "redis", "storage", "tutor_skill"}
    is_ready = all(bool(checks[k]["ok"]) for k in core_keys)
    return {"status": "ready" if is_ready else "degraded", "checks": checks}

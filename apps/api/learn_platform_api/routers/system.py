from fastapi import APIRouter

from learn_platform_api.settings import get_settings

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/info")
def system_info() -> dict[str, object]:
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "storage": {"configured": bool(settings.storage_root)},
    }

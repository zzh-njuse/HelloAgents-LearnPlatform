import os
from pathlib import Path

import httpx
from redis import Redis
from sqlalchemy import text
from sqlalchemy.engine import Engine


def check_postgres(engine: Engine) -> dict[str, object]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"ok": True, "detail": "可用"}
    except Exception:
        return {"ok": False, "detail": "不可用"}


def check_qdrant(url: str, timeout: float) -> dict[str, object]:
    try:
        response = httpx.get(f"{url.rstrip('/')}/readyz", timeout=timeout)
        response.raise_for_status()
        return {"ok": True, "detail": "可用"}
    except Exception:
        return {"ok": False, "detail": "不可用"}


def check_redis(url: str, timeout: float) -> dict[str, object]:
    client: Redis | None = None
    try:
        client = Redis.from_url(
            url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
            decode_responses=True,
        )
        return {"ok": bool(client.ping()), "detail": "可用"}
    except Exception:
        return {"ok": False, "detail": "不可用"}
    finally:
        if client is not None:
            client.close()


def check_storage(path: Path) -> dict[str, object]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir() or not os.access(path, os.W_OK):
            raise OSError("storage root is not writable")
        return {"ok": True, "detail": "可写"}
    except OSError:
        return {"ok": False, "detail": "不可写"}

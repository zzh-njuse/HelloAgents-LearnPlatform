import os
from pathlib import Path

import httpx
from redis import Redis
from sqlalchemy import text
from sqlalchemy.engine import Engine

from academic_companion.teaching_skills import SkillUnavailable, current_published, load_skill


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
        ok = bool(client.ping())
        return {"ok": ok, "detail": "可用" if ok else "不可用"}
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


def check_tutor_skill() -> dict[str, object]:
    """Verify the allow-listed teaching skill resolves and hash-verifies (corr 3.7).

    Mirrors ADR 005 §3.2: the published skill must exist, its metadata must match
    and its normalized file hash must be computable. The detail is a stable,
    non-sensitive label only — never the path, prompt body or content hash.
    """
    try:
        skill_id, version = current_published()
        load_skill(skill_id, version)
    except SkillUnavailable:
        return {"ok": False, "detail": "教学 Skill 不可用"}
    except Exception:
        return {"ok": False, "detail": "教学 Skill 不可用"}
    return {"ok": True, "detail": "可用"}

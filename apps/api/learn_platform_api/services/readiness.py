import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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


# ---------------------------------------------------------------------------
# MCP readiness — reads from capability status projection with TTL
# (correction 004 §3/§4: enabled ≠ ready; readiness from projection, not config)
# ---------------------------------------------------------------------------

# Default TTL for capability status projections (seconds)
DEFAULT_CAPABILITY_TTL_SECONDS = 30


def _read_capability_projection(db: Session, capability_id: str) -> dict[str, object] | None:
    """Read a capability status projection from the database.

    Per correction 004 §3/§4: readiness must come from an actual, TTL-bearing
    projection written by a probe/worker — not from enabled=True or URL non-empty.

    Returns None if no projection exists or the projection has expired.
    Returns the projection dict if it exists and is within TTL.
    """
    from learn_platform_api.db.models import McpCapabilityStatus

    row = db.scalar(
        select(McpCapabilityStatus).where(
            McpCapabilityStatus.capability_id == capability_id,
        )
    )
    if row is None:
        return None

    # Check TTL
    now = datetime.now(timezone.utc)
    checked_at = row.checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)

    age_seconds = (now - checked_at).total_seconds()
    if age_seconds > row.ttl_seconds:
        return None  # Expired — caller treats as unavailable

    return {
        "ok": row.status == "ready",
        "status": row.status,
        "detail": row.detail or "不可用",
        "verified_schema_hash": row.verified_schema_hash,
        "checked_at": row.checked_at.isoformat(),
        "ttl_seconds": row.ttl_seconds,
    }


def check_code_execution(settings, db: Session | None = None) -> dict[str, object]:
    """Check code execution MCP capability readiness.

    Per correction 004 §3: readiness must come from an actual capability
    status projection with TTL — not from URL non-empty or MCP handshake
    on every request.

    The projection is written by a probe/worker that holds the execution
    backend URL and performs the real MCP handshake. The API only reads
    the projection. This preserves network isolation: the API does not
    need to reach the execution MCP or the execution backend.

    enabled ≠ ready:
    - enabled: the capability is configured in settings
    - ready: a non-expired successful projection exists in the DB

    If no DB session is available (e.g. startup), falls back to checking
    configuration only — but never claims ready just because URL is set.
    """
    # The API deliberately does not need the adapter URL.  When a DB session is
    # available, the probe-owned projection is the sole readiness authority.
    if db is not None:
        projection = _read_capability_projection(db, "code_execution")
        if projection is not None:
            return projection
        # No valid projection means the backend has not been verified recently.
        return {"ok": False, "detail": "后端未验证"}

    # Without the projection store, never claim readiness from configuration.
    return {
        "ok": False,
        "detail": "后端未验证" if settings.mcp_execution_adapter_url else "未配置",
    }


def check_science_tool(settings, db: Session | None = None) -> dict[str, object]:
    """Check Wolfram science tool capability readiness.

    Per correction 004 §4: readiness must come from an actual capability
    status projection with TTL — not from enabled=True.

    The projection is written by a probe/worker that holds the Wolfram
    remote config and performs the real MCP handshake. The API only reads
    the projection. This preserves the security boundary: the API does
    not hold the Wolfram secret.

    enabled ≠ ready:
    - enabled: wolfram_mcp_enabled is True
    - ready: a non-expired successful projection exists in the DB

    If enabled but no valid projection exists, the capability is in
    "verification pending" state — not ready, not unavailable.
    """
    # Not enabled → unavailable
    if not settings.wolfram_mcp_enabled:
        return {"ok": False, "detail": "未启用"}

    # Read from projection if DB is available
    if db is not None:
        projection = _read_capability_projection(db, "science_computation")
        if projection is not None:
            return projection
        # Enabled but no valid projection — verification pending
        return {"ok": False, "detail": "验证待确认"}

    # No DB — enabled but cannot verify
    return {"ok": False, "detail": "验证待确认"}


# ---------------------------------------------------------------------------
# Capability projection writer — called by probe/worker
# ---------------------------------------------------------------------------

def write_capability_projection(
    db: Session,
    capability_id: str,
    status: str,
    detail: str,
    verified_schema_hash: str = "",
    ttl_seconds: int = DEFAULT_CAPABILITY_TTL_SECONDS,
) -> None:
    """Write or update a capability status projection.

    Per correction 004 §3/§4: only the probe/worker that holds the remote
    config should call this. The API only reads projections.

    Args:
        status: "ready" | "unavailable" | "verification_pending" | "disabled"
        detail: Desensitized, stable reason — never URLs, credentials, or remote body
        verified_schema_hash: Combined canonical hash from successful handshake
        ttl_seconds: How long this projection remains valid
    """
    from learn_platform_api.db.models import McpCapabilityStatus

    row = db.scalar(
        select(McpCapabilityStatus).where(
            McpCapabilityStatus.capability_id == capability_id,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = McpCapabilityStatus(
            capability_id=capability_id,
            status=status,
            detail=detail,
            verified_schema_hash=verified_schema_hash,
            checked_at=now,
            ttl_seconds=ttl_seconds,
        )
        db.add(row)
    else:
        row.status = status
        row.detail = detail
        row.verified_schema_hash = verified_schema_hash
        row.checked_at = now
        row.ttl_seconds = ttl_seconds
    db.flush()

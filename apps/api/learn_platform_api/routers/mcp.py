"""MCP capability and code lab run API router.

Spec 004 §5, ADR 006 §2.2/2.5/2.7/2.8.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    CodeLabJob,
    CodeLabRun,
    Workspace,
    WorkspaceMcpPolicy,
    TutorTurnCodeRun,
)
from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.mcp import (
    CodeRunCreate,
    CodeRunDetailRead,
    CodeRunRead,
    CodeRunSafeSummary,
    McpCapabilityRead,
    McpPolicyPatch,
    McpPolicyRead,
)
from learn_platform_api.services.queue import enqueue_code_lab_job
from learn_platform_api.settings import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["mcp"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ws(db: Session, workspace_id: str) -> Workspace:
    ws = db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    return ws


# ---------------------------------------------------------------------------
# Capability readiness
# ---------------------------------------------------------------------------

@router.get("/mcp-capabilities", response_model=list[McpCapabilityRead])
def list_mcp_capabilities(
    workspace_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _ws(db, workspace_id)
    caps: list[McpCapabilityRead] = []

    # Code execution capability — per correction 004 §3: read from projection
    from learn_platform_api.services.readiness import check_code_execution
    exec_readiness = check_code_execution(settings, db=db)
    caps.append(McpCapabilityRead(
        capability="code_execution",
        status="ready" if exec_readiness["ok"] else "unavailable",
        detail=str(exec_readiness.get("detail", "不可用")),
    ))

    # Science computation capability — per correction 004 §4: read from projection
    from learn_platform_api.services.readiness import check_science_tool
    science_readiness = check_science_tool(settings, db=db)
    caps.append(McpCapabilityRead(
        capability="science_computation",
        status="ready" if science_readiness["ok"] else "unavailable",
        detail=str(science_readiness.get("detail", "不可用")),
    ))

    return caps


# ---------------------------------------------------------------------------
# MCP Policy
# ---------------------------------------------------------------------------

@router.get("/mcp-policy", response_model=McpPolicyRead)
def get_mcp_policy(
    workspace_id: str,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    policy = db.scalar(
        select(WorkspaceMcpPolicy).where(WorkspaceMcpPolicy.workspace_id == workspace_id)
    )
    if policy is None:
        return McpPolicyRead(
            workspace_id=workspace_id,
            code_execution_enabled=False,
            revision=0,
        )
    return McpPolicyRead(
        workspace_id=policy.workspace_id,
        code_execution_enabled=bool(policy.code_execution_enabled),
        revision=policy.revision,
    )


@router.patch("/mcp-policy", response_model=McpPolicyRead)
def patch_mcp_policy(
    workspace_id: str,
    patch: McpPolicyPatch,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    policy = db.scalar(
        select(WorkspaceMcpPolicy)
        .where(WorkspaceMcpPolicy.workspace_id == workspace_id)
        .with_for_update()
    )
    if policy is None:
        policy = WorkspaceMcpPolicy(
            workspace_id=workspace_id,
            code_execution_enabled=1 if patch.code_execution_enabled else 0,
        )
        db.add(policy)
    else:
        policy.code_execution_enabled = 1 if patch.code_execution_enabled else 0
        policy.revision += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        policy = db.scalar(
            select(WorkspaceMcpPolicy)
            .where(WorkspaceMcpPolicy.workspace_id == workspace_id)
            .with_for_update()
        )
        if policy is None:
            raise HTTPException(status_code=409, detail="mcp_policy_conflict")
        policy.code_execution_enabled = 1 if patch.code_execution_enabled else 0
        policy.revision += 1
        db.commit()
    db.refresh(policy)
    return McpPolicyRead(
        workspace_id=policy.workspace_id,
        code_execution_enabled=bool(policy.code_execution_enabled),
        revision=policy.revision,
    )


# ---------------------------------------------------------------------------
# Code Lab Runs
# ---------------------------------------------------------------------------

@router.post("/code-runs", response_model=CodeRunRead, status_code=202)
def create_code_run(
    workspace_id: str,
    body: CodeRunCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    ws = _ws(db, workspace_id)

    # Check policy
    policy = db.scalar(
        select(WorkspaceMcpPolicy).where(WorkspaceMcpPolicy.workspace_id == workspace_id)
    )
    if policy is None or not policy.code_execution_enabled:
        raise HTTPException(status_code=403, detail="code_execution_not_enabled")

    # The API does not hold the adapter URL.  A fresh probe projection is the
    # authority for whether the isolated execution chain may accept work.
    from learn_platform_api.services.readiness import _read_capability_projection

    projection = _read_capability_projection(db, "code_execution")
    if projection is None or not projection.get("ok"):
        raise HTTPException(status_code=503, detail="execution_backend_unavailable")

    # Compute request hash for idempotency
    request_data = body.model_dump_json()
    request_hash = hashlib.sha256(request_data.encode()).hexdigest()

    # Idempotency check
    existing_job = db.scalar(
        select(CodeLabJob)
        .where(
            CodeLabJob.workspace_id == workspace_id,
            CodeLabJob.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        if existing_job.request_hash == request_hash:
            # Same request — return existing run
            run = db.scalar(select(CodeLabRun).where(CodeLabRun.id == existing_job.run_id))
            return _run_to_read(run)
        else:
            raise HTTPException(status_code=409, detail="idempotency_key_conflict")

    # Create run and job
    run_id = str(uuid4())
    run = CodeLabRun(
        id=run_id,
        workspace_id=workspace_id,
        course_id=body.course_id,
        course_version_id=body.course_version_id,
        lesson_id=body.lesson_id,
        lesson_version_id=body.lesson_version_id,
        language=body.language,
        source_code=body.source_code,
        stdin=body.stdin,
        status="queued",
    )
    db.add(run)
    db.flush()

    job = CodeLabJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        run_id=run_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="queued",
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_job = db.scalar(
            select(CodeLabJob).where(
                CodeLabJob.workspace_id == workspace_id,
                CodeLabJob.idempotency_key == idempotency_key,
            )
        )
        if existing_job is None or existing_job.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="idempotency_key_conflict")
        existing_run = db.scalar(
            select(CodeLabRun).where(CodeLabRun.id == existing_job.run_id)
        )
        if existing_run is None:
            raise HTTPException(status_code=409, detail="idempotency_key_conflict")
        return _run_to_read(existing_run)
    db.refresh(job)

    try:
        enqueue_code_lab_job(settings, job.id)
    except Exception:
        # Enqueue failed — mark job as queue_failed but keep the DB records
        # so the client can retry. Do NOT raise 500 after committing.
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "代码运行队列暂时不可用，可稍后重试"
        run.status = "queue_failed"
        db.commit()
        db.refresh(run)

    return _run_to_read(run)


@router.get("/code-runs", response_model=list[CodeRunRead])
def list_code_runs(
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    rows = db.scalars(
        select(CodeLabRun)
        .where(CodeLabRun.workspace_id == workspace_id, CodeLabRun.deleted_at.is_(None))
        .order_by(CodeLabRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_run_to_read(r) for r in rows]


@router.get("/code-runs/{run_id}", response_model=CodeRunDetailRead)
def get_code_run(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    run = db.scalar(
        select(CodeLabRun)
        .where(
            CodeLabRun.id == run_id,
            CodeLabRun.workspace_id == workspace_id,
            CodeLabRun.deleted_at.is_(None),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="code_run_not_found")
    return _run_to_detail(run)


@router.post("/code-runs/{run_id}/cancel", response_model=CodeRunRead)
def cancel_code_run(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    run = db.scalar(
        select(CodeLabRun)
        .where(CodeLabRun.id == run_id, CodeLabRun.workspace_id == workspace_id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="code_run_not_found")
    if run.status not in ("queued", "running", "retry_wait"):
        raise HTTPException(status_code=409, detail="run_not_cancellable")

    now = _now()
    # queued/retry_wait → canceled immediately (no worker to signal)
    # running → cancel_requested (worker/reconciler will converge)
    if run.status in ("queued", "retry_wait"):
        run.status = "canceled"
        run.completed_at = now
        # Terminate the job immediately too
        db.execute(
            update(CodeLabJob)
            .where(CodeLabJob.run_id == run_id, CodeLabJob.status.in_(("queued", "running", "retry_wait")))
            .values(status="canceled", completed_at=now, lease_expires_at=None, next_attempt_at=None)
        )
    else:
        run.status = "cancel_requested"
        db.execute(
            update(CodeLabJob)
            .where(CodeLabJob.run_id == run_id, CodeLabJob.status.in_(("queued", "running", "retry_wait")))
            .values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None)
        )
    db.commit()
    db.refresh(run)
    return _run_to_read(run)


@router.delete("/code-runs/{run_id}", status_code=204)
def delete_code_run(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    run = db.scalar(
        select(CodeLabRun)
        .where(CodeLabRun.id == run_id, CodeLabRun.workspace_id == workspace_id, CodeLabRun.deleted_at.is_(None))
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="code_run_not_found")

    now = _now()

    # Cancel active job first (prevent late results from being committed)
    db.execute(
        update(CodeLabJob)
        .where(CodeLabJob.run_id == run_id, CodeLabJob.status.in_(("queued", "running", "retry_wait")))
        .values(status="canceled", completed_at=now, lease_expires_at=None, next_attempt_at=None)
    )

    # Delete associated TutorTurnCodeRun links
    db.execute(
        TutorTurnCodeRun.__table__.delete().where(TutorTurnCodeRun.code_lab_run_id == run_id)
    )

    # Delete AgentToolCalls and AgentRun for this run's job
    job = db.scalar(select(CodeLabJob).where(CodeLabJob.run_id == run_id))
    if job is not None:
        db.execute(
            AgentToolCall.__table__.delete().where(
                AgentToolCall.agent_run_id.in_(
                    select(AgentRun.id).where(AgentRun.code_lab_job_id == job.id)
                )
            )
        )
        db.execute(AgentRun.__table__.delete().where(AgentRun.code_lab_job_id == job.id))

    # Clear ALL private content per ADR 006 §2.8 / Spec 004 §9
    run.source_code = ""
    run.stdin = ""
    run.compile_output = ""
    run.stdout = ""
    run.stderr = ""
    run.deleted_at = now

    db.commit()


# ---------------------------------------------------------------------------
# Safe summary for Tutor consumption
# ---------------------------------------------------------------------------

@router.get("/code-runs/{run_id}/safe-summary", response_model=CodeRunSafeSummary)
def get_code_run_safe_summary(
    workspace_id: str,
    run_id: str,
    db: Session = Depends(get_db),
):
    _ws(db, workspace_id)
    run = db.scalar(
        select(CodeLabRun)
        .where(CodeLabRun.id == run_id, CodeLabRun.workspace_id == workspace_id, CodeLabRun.deleted_at.is_(None))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="code_run_not_found")
    return CodeRunSafeSummary(
        id=run.id,
        language=run.language,
        status=run.status,
        exit_code=run.exit_code,
        duration_ms=run.duration_ms,
        runtime=run.runtime,
        stdout_truncated=bool(run.stdout_truncated),
        stderr_truncated=bool(run.stderr_truncated),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_to_read(run: CodeLabRun) -> CodeRunRead:
    return CodeRunRead(
        id=run.id,
        workspace_id=run.workspace_id,
        language=run.language,
        status=run.status,
        course_id=run.course_id,
        lesson_id=run.lesson_id,
        exit_code=run.exit_code,
        duration_ms=run.duration_ms,
        runtime=run.runtime,
        stdout_truncated=bool(run.stdout_truncated),
        stderr_truncated=bool(run.stderr_truncated),
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        deleted_at=run.deleted_at.isoformat() if run.deleted_at else None,
    )


def _run_to_detail(run: CodeLabRun) -> CodeRunDetailRead:
    return CodeRunDetailRead(
        id=run.id,
        workspace_id=run.workspace_id,
        language=run.language,
        status=run.status,
        course_id=run.course_id,
        lesson_id=run.lesson_id,
        exit_code=run.exit_code,
        duration_ms=run.duration_ms,
        runtime=run.runtime,
        stdout_truncated=bool(run.stdout_truncated),
        stderr_truncated=bool(run.stderr_truncated),
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        deleted_at=run.deleted_at.isoformat() if run.deleted_at else None,
        source_code=run.source_code,
        stdin=run.stdin,
        compile_output=run.compile_output,
        stdout=run.stdout,
        stderr=run.stderr,
    )

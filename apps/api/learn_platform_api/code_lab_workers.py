"""Code lab worker — executes code runs via the MCP execution adapter.

Follows the same claim/lease/heartbeat/cancel/retry/final-authority pattern
as the existing practice and tutor workers (Spec 004 §8, ADR 006 §2.4).

The worker ONLY calls the execution MCP via the official Python SDK
(Streamable HTTP). It never calls Judge0/Piston HTTP directly.
"""

import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from learn_platform_api.db.models import AgentRun, AgentToolCall, CodeLabJob, CodeLabRun, Workspace, WorkspaceMcpPolicy
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.settings import get_settings

logger = logging.getLogger(__name__)

RETRYABLE_CODES = {"backend_unavailable", "backend_timeout", "duplicate_delivery"}

ERROR_MESSAGES = {
    "backend_unavailable": "执行后端暂不可用",
    "backend_timeout": "执行后端超时",
    "invalid_tool_result": "执行结果未通过 schema 校验",
    "code_lab_canceled": "代码运行已取消",
    "policy_disabled": "代码实验室未启用",
    "workspace_deleting": "工作空间正在删除",
    "schema_drift": "执行后端 schema 漂移",
    "duplicate_delivery": "重复投递，已跳过",
    "unknown_error": "未知执行错误",
}

# MCP snapshot constants — single canonical source from the shared contract.
# Per correction 004 §2: the worker imports from the shared contract package
# that both the API/worker image and the MCP execution image install.
# No fallback Pydantic models, no duplicated schemas, no hand-written hashes.
MCP_SERVER_NAME = "learn-platform-code-execution"
MCP_SERVER_VERSION = "1.0.0"
MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_TOOL_NAME = "run_code"
# Per correction 004 §2: import from the single canonical shared contract.
# If this import fails, the worker cannot validate schema — that is correct,
# never silently fall back to a local copy that may drift.
from shared.mcp_execution_contract import (
    INPUT_SCHEMA_HASH as MCP_INPUT_SCHEMA_HASH,
    OUTPUT_SCHEMA_HASH as MCP_OUTPUT_SCHEMA_HASH,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Heartbeat / lease maintenance
# ---------------------------------------------------------------------------

def heartbeat_code_lab_job(job_id: str, worker_id: str, settings) -> bool:
    now = _now()
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(
            update(CodeLabJob)
            .where(CodeLabJob.id == job_id, CodeLabJob.status == "running", CodeLabJob.worker_id == worker_id)
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.code_lab_lease_seconds))
        ).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_code_lab_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()

    def loop() -> None:
        while not stopped.wait(settings.code_lab_heartbeat_seconds):
            try:
                if not heartbeat_code_lab_job(job_id, worker_id, settings):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=loop, name=f"code-lab-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------

def run_code_lab_job(job_id: str) -> None:
    """Entry point for rq worker: execute a code lab job."""
    settings = get_settings()
    worker_id = f"{socket.gethostname()}-{threading.current_thread().ident}"

    with SessionLocal() as db:
        # Claim the job
        job = db.scalar(
            select(CodeLabJob)
            .where(CodeLabJob.id == job_id, CodeLabJob.status.in_(("queued", "retry_wait")))
            .with_for_update()
        )
        if job is None:
            return

        job.status = "running"
        job.worker_id = worker_id
        job.lease_expires_at = _now() + timedelta(seconds=settings.code_lab_lease_seconds)
        job.attempt_count += 1
        db.commit()

    # Execute with lease maintenance
    try:
        with maintain_code_lab_lease(job_id, worker_id, settings) as lease_lost:
            if lease_lost.is_set():
                return
            _execute_job(job_id, worker_id, settings)
    except Exception as exc:
        logger.exception("code lab job %s failed: %s", job_id, exc)
        _mark_failed(job_id, str(exc)[:500], settings)


def _execute_job(job_id: str, worker_id: str, settings) -> None:
    """Execute the code run via the MCP execution adapter (Streamable HTTP)."""
    from learn_platform_api.services.code_lab_execution import (
        execute_code_run_sync,
        BackendUnavailableError,
        InvalidToolResultError,
        SchemaDriftError,
        ExecutionMcpError,
    )

    with SessionLocal() as db:
        # Final authority recheck — all six checks per Spec 004 §8
        job = db.scalar(select(CodeLabJob).where(CodeLabJob.id == job_id).with_for_update())
        if job is None or job.status != "running":
            return  # Job was canceled or lease lost

        # Check 1: owner — this worker must still own the job
        if job.worker_id != worker_id:
            return

        # Check 2: lease — must not be expired
        now = _now()
        if job.lease_expires_at is None or job.lease_expires_at <= now:
            return

        # Check 3: Run not deleted
        run = db.scalar(select(CodeLabRun).where(CodeLabRun.id == job.run_id).with_for_update())
        if run is None or run.deleted_at is not None:
            _mark_failed(job_id, "code_lab_canceled", settings)
            return

        # Check 4: Workspace still active
        ws = db.scalar(select(Workspace).where(Workspace.id == job.workspace_id).with_for_update())
        if ws is None or ws.lifecycle_status != "active":
            _mark_failed(job_id, "workspace_deleting", settings)
            return

        # Check 5: Policy still enabled
        policy = db.scalar(
            select(WorkspaceMcpPolicy).where(WorkspaceMcpPolicy.workspace_id == job.workspace_id)
        )
        if policy is None or not policy.code_execution_enabled:
            _mark_failed(job_id, "policy_disabled", settings)
            return

        # Check 6: Adapter configured
        if not settings.mcp_execution_adapter_url:
            _mark_failed(job_id, "backend_unavailable", settings)
            return

        # Check 7: Capability schema snapshot not drifted from expected constants.
        # Per §2.3: worker must verify that the stored capability snapshot on the Run
        # (if already set from a previous attempt) still matches expected constants.
        if (run.mcp_input_schema_hash and run.mcp_input_schema_hash != MCP_INPUT_SCHEMA_HASH) or \
           (run.mcp_output_schema_hash and run.mcp_output_schema_hash != MCP_OUTPUT_SCHEMA_HASH):
            _mark_failed(job_id, "schema_drift", settings)
            return

        # Create AgentRun for tracing
        agent_run = AgentRun(
            code_lab_job_id=job.id,
            workspace_id=job.workspace_id,
            role="code_execution",
            attempt_number=job.attempt_count,
            status="running",
            step_count=0,
        )
        db.add(agent_run)
        db.flush()

        # Execute via MCP client (Streamable HTTP, official SDK)
        try:
            result, handshake = execute_code_run_sync(
                request_id=run.id,
                language=run.language,
                source_code=run.source_code,
                stdin=run.stdin,
                settings=settings,
            )
        except BackendUnavailableError as exc:
            db.rollback()
            _mark_failed(job_id, "backend_unavailable", settings)
            return
        except InvalidToolResultError as exc:
            db.rollback()
            _mark_failed(job_id, "invalid_tool_result", settings)
            return
        except SchemaDriftError as exc:
            db.rollback()
            _mark_failed(job_id, "schema_drift", settings)
            return
        except ExecutionMcpError as exc:
            db.rollback()
            _mark_failed(job_id, "unknown_error", settings)
            return

        # Post-MCP-call final authority recheck — full six-way check
        # (prevent late results after cancel/delete/policy change/owner change/lease expiry)
        db.refresh(job)
        if job.status != "running" or job.worker_id != worker_id:
            return  # Canceled or owner changed while we were executing
        if job.lease_expires_at is not None and job.lease_expires_at <= _now():
            return  # Lease expired

        db.refresh(run)
        if run.deleted_at is not None:
            return  # Deleted while we were executing

        db.refresh(ws)
        if ws.lifecycle_status != "active":
            return  # Workspace deleting

        # Re-check policy (could have been disabled during execution)
        db.refresh(policy) if policy else None
        policy_refreshed = db.scalar(
            select(WorkspaceMcpPolicy).where(WorkspaceMcpPolicy.workspace_id == job.workspace_id)
        )
        if policy_refreshed is None or not policy_refreshed.code_execution_enabled:
            return  # Policy disabled during execution

        # Re-check capability schema snapshot — handshake must match expected constants.
        # Per §2.3: the authoritative handshake snapshot must be consistent with
        # what the worker expects; drift means the backend changed under us.
        if handshake.input_schema_hash != MCP_INPUT_SCHEMA_HASH or \
           handshake.output_schema_hash != MCP_OUTPUT_SCHEMA_HASH:
            _mark_failed(job_id, "schema_drift", settings)
            return

        # Update run with result
        run.status = result.status
        run.exit_code = result.exit_code
        run.compile_output = result.compile_output
        run.stdout = result.stdout
        run.stderr = result.stderr
        run.duration_ms = result.duration_ms
        run.runtime = result.runtime
        run.stdout_truncated = 1 if result.stdout_truncated else 0
        run.stderr_truncated = 1 if result.stderr_truncated else 0
        run.completed_at = _now()
        run.updated_at = _now()

        # Update MCP snapshot — use the authoritative handshake result, not local constants
        run.mcp_server_name = handshake.server_name
        run.mcp_server_version = handshake.server_version
        run.mcp_protocol_version = handshake.protocol_version
        run.mcp_tool_name = handshake.tool_name
        run.mcp_input_schema_hash = handshake.input_schema_hash
        run.mcp_output_schema_hash = handshake.output_schema_hash

        # Write AgentToolCall (safe metadata only — no code/output)
        tool_call = AgentToolCall(
            agent_run_id=agent_run.id,
            workspace_id=job.workspace_id,
            tool_name="McpCodeExecution",
            ordinal=1,
            status="succeeded",
            input_hash=job.request_hash,
            result_count=1,
            latency_ms=result.duration_ms,
        )
        db.add(tool_call)

        # Update job
        job.status = "succeeded"
        job.completed_at = _now()

        # Update AgentRun
        agent_run.status = "succeeded"
        agent_run.step_count = 1
        agent_run.completed_at = _now()

        db.commit()


def _mark_failed(job_id: str, error: str, settings) -> None:
    """Mark job as failed or retry_wait depending on error code."""
    with SessionLocal() as db:
        job = db.scalar(select(CodeLabJob).where(CodeLabJob.id == job_id).with_for_update())
        if job is None:
            return

        error_code = error if error in RETRYABLE_CODES else "unknown_error"

        if error_code in RETRYABLE_CODES and job.attempt_count < settings.code_lab_max_attempts:
            job.status = "retry_wait"
            job.next_attempt_at = _now() + timedelta(seconds=30 * (2 ** (job.attempt_count - 1)))
            job.error_code = error_code
            job.error_message = ERROR_MESSAGES.get(error_code, error)[:500]
        else:
            job.status = "failed"
            job.error_code = error_code
            job.error_message = ERROR_MESSAGES.get(error_code, error)[:500]
            job.completed_at = _now()

            # Also mark the run as failed
            run = db.scalar(select(CodeLabRun).where(CodeLabRun.id == job.run_id))
            if run is not None and run.status in ("queued", "running"):
                run.status = "failed"
                run.completed_at = _now()

        db.commit()

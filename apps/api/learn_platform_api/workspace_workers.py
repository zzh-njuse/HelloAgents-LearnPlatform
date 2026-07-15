import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from learn_platform_api.db.models import WorkspaceDeletionJob
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.workspace_deletion import execute_deletion
from learn_platform_api.settings import get_settings


logger = logging.getLogger("learn_platform_api.workspace_deletion")


def heartbeat_workspace_deletion(job_id: str, worker_id: str, settings) -> bool:
    current = datetime.now(timezone.utc)
    with SessionLocal() as db:
        updated = db.execute(
            update(WorkspaceDeletionJob)
            .where(
                WorkspaceDeletionJob.id == job_id,
                WorkspaceDeletionJob.status == "running",
                WorkspaceDeletionJob.worker_id == worker_id,
            )
            .values(
                heartbeat_at=current,
                lease_expires_at=current + timedelta(seconds=settings.ingestion_lease_seconds),
            )
        ).rowcount
        db.commit()
        return bool(updated)


@contextmanager
def maintain_workspace_deletion_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()

    def loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_workspace_deletion(job_id, worker_id, settings):
                    lost.set()
                    return
            except Exception:
                logger.exception("workspace_deletion_heartbeat_failed job_id=%s", job_id)
                lost.set()
                return

    thread = threading.Thread(target=loop, name=f"workspace-deletion-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=5)


def run_workspace_deletion_job(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        current = datetime.now(timezone.utc)
        claimed = db.execute(
            update(WorkspaceDeletionJob)
            .where(WorkspaceDeletionJob.id == job_id, WorkspaceDeletionJob.status.in_({"queued", "retry_wait"}))
            .values(
                status="running",
                attempt_count=WorkspaceDeletionJob.attempt_count + 1,
                worker_id=worker_id,
                heartbeat_at=current,
                lease_expires_at=current + timedelta(seconds=settings.ingestion_lease_seconds),
                next_attempt_at=None,
                error_code=None,
                error_message=None,
            )
        ).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(WorkspaceDeletionJob, job_id)
        try:
            with maintain_workspace_deletion_lease(job_id, worker_id, settings) as lease_lost:
                execute_deletion(db, settings, job)
                if lease_lost.is_set():
                    raise RuntimeError("workspace_deletion_lease_lost")
            db.commit()
        except Exception:
            logger.exception("workspace_deletion_failed job_id=%s", job_id)
            db.rollback()
            job = db.get(WorkspaceDeletionJob, job_id)
            if job is None or job.status != "running" or job.worker_id != worker_id:
                return
            retryable = job.attempt_count < settings.ingestion_max_attempts
            job.status = "retry_wait" if retryable else "failed"
            job.error_code = "workspace_cleanup_failed"
            job.error_message = "Workspace 清理暂时失败，可稍后重试"
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=5) if retryable else None
            db.commit()

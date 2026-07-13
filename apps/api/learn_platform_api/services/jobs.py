import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import IngestionJob
from learn_platform_api.services.batches import reconcile_stale_batches
from learn_platform_api.services.queue import enqueue_ingestion_job
from learn_platform_api.settings import Settings


logger = logging.getLogger("learn_platform_api.jobs")


def reconcile_jobs(db: Session, settings: Settings) -> int:
    now = datetime.now(timezone.utc)
    recoverable_jobs = list(db.execute(
        select(IngestionJob).where(
            (
                (IngestionJob.status == "running")
                & IngestionJob.lease_expires_at.is_not(None)
                & (IngestionJob.lease_expires_at < now)
            )
            | (
                (IngestionJob.status == "retry_wait")
                & IngestionJob.next_attempt_at.is_not(None)
                & (IngestionJob.next_attempt_at <= now)
            )
            | (
                (IngestionJob.status == "queued")
                & (IngestionJob.updated_at < now - timedelta(seconds=settings.ingestion_lease_seconds))
            )
        ).with_for_update(skip_locked=True)
    ).scalars())
    for job in recoverable_jobs:
        job.status = "queued"
        job.worker_id = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.next_attempt_at = None
        job.updated_at = now
    db.commit()
    for job in recoverable_jobs:
        try:
            enqueue_ingestion_job(settings, job.id)
        except Exception:
            logger.exception("reconcile_enqueue_failed job_id=%s", job.id)
            job.status = "queue_failed"
            job.error_code = "queue_unavailable"
            job.error_message = "任务队列暂不可用，可稍后重试"
    if recoverable_jobs:
        db.commit()
    stale_batches = reconcile_stale_batches(db, now - timedelta(seconds=settings.ingestion_lease_seconds))
    if recoverable_jobs or stale_batches:
        logger.info(
            "ingestion_reconciled recovered_jobs=%s reconciled_batches=%s",
            len(recoverable_jobs),
            stale_batches,
        )
    return len(recoverable_jobs) + stale_batches

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import CourseGenerationJob, IngestionJob, TutorSession, TutorTurn, WorkspaceDeletionJob
from learn_platform_api.services.batches import reconcile_stale_batches
from learn_platform_api.services.queue import enqueue_course_generation_job, enqueue_ingestion_job, enqueue_tutor_session_deletion, enqueue_tutor_turn, enqueue_workspace_deletion_job
from learn_platform_api.settings import Settings

logger = logging.getLogger("learn_platform_api.jobs")


def reconcile_jobs(db: Session, settings: Settings) -> int:
    current = datetime.now(timezone.utc)
    stale_before = current - timedelta(seconds=settings.ingestion_lease_seconds)
    ingestion_jobs = list(db.scalars(select(IngestionJob).where(
        ((IngestionJob.status == "running") & IngestionJob.lease_expires_at.is_not(None) & (IngestionJob.lease_expires_at < current))
        | ((IngestionJob.status == "retry_wait") & IngestionJob.next_attempt_at.is_not(None) & (IngestionJob.next_attempt_at <= current))
        | ((IngestionJob.status == "queued") & (IngestionJob.updated_at < stale_before))
    ).with_for_update(skip_locked=True)))
    for job in ingestion_jobs:
        job.status = "queued"; job.worker_id = None; job.lease_expires_at = None; job.heartbeat_at = None; job.next_attempt_at = None; job.updated_at = current
    db.commit()
    for job in ingestion_jobs:
        try: enqueue_ingestion_job(settings, job.id)
        except Exception:
            logger.exception("reconcile_enqueue_failed job_id=%s", job.id); job.status = "queue_failed"; job.error_code = "queue_unavailable"; job.error_message = "任务队列暂时不可用，可稍后重试"
    if ingestion_jobs: db.commit()

    stale_batches = reconcile_stale_batches(db, stale_before)
    course_jobs = list(db.scalars(select(CourseGenerationJob).where(
        ((CourseGenerationJob.status == "running") & CourseGenerationJob.lease_expires_at.is_not(None) & (CourseGenerationJob.lease_expires_at < current))
        | ((CourseGenerationJob.status == "retry_wait") & CourseGenerationJob.next_attempt_at.is_not(None) & (CourseGenerationJob.next_attempt_at <= current))
        | ((CourseGenerationJob.status == "queued") & (CourseGenerationJob.updated_at < stale_before))
    ).with_for_update(skip_locked=True)))
    for job in course_jobs:
        job.status = "queued"; job.worker_id = None; job.lease_expires_at = None; job.heartbeat_at = None; job.next_attempt_at = None; job.updated_at = current
    db.commit()
    for job in course_jobs:
        try: enqueue_course_generation_job(settings, job.id)
        except Exception:
            logger.exception("course_generation_reconcile_enqueue_failed job_id=%s", job.id); job.status = "queue_failed"; job.error_code = "queue_failed"; job.error_message = "课程生成队列暂时不可用"
    if course_jobs: db.commit()

    canceled_course_jobs = list(db.scalars(select(CourseGenerationJob).where(
        CourseGenerationJob.status == "cancel_requested"
    ).with_for_update(skip_locked=True)))
    for job in canceled_course_jobs:
        job.status = "canceled"
        job.error_code = "generation_canceled"
        job.error_message = "课程生成已取消"
        job.worker_id = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.next_attempt_at = None
        job.updated_at = current
    if canceled_course_jobs:
        db.commit()

    tutor_turns = list(db.scalars(select(TutorTurn).where(
        ((TutorTurn.status == "running") & TutorTurn.lease_expires_at.is_not(None) & (TutorTurn.lease_expires_at < current))
        | ((TutorTurn.status == "retry_wait") & TutorTurn.next_attempt_at.is_not(None) & (TutorTurn.next_attempt_at <= current))
        | ((TutorTurn.status == "queued") & (TutorTurn.updated_at < stale_before))
    ).with_for_update(skip_locked=True)))
    for turn in tutor_turns:
        turn.status = "queued"; turn.worker_id = None; turn.lease_expires_at = None; turn.next_attempt_at = None; turn.updated_at = current
    db.commit()
    for turn in tutor_turns:
        try: enqueue_tutor_turn(settings, turn.id)
        except Exception:
            logger.exception("tutor_reconcile_enqueue_failed turn_id=%s", turn.id); turn.status = "queue_failed"; turn.error_code = "queue_unavailable"; turn.error_message = "Tutor 队列暂时不可用"
    if tutor_turns: db.commit()

    deleting_sessions = list(db.scalars(select(TutorSession).where(TutorSession.status == "deleting", TutorSession.updated_at < stale_before).with_for_update(skip_locked=True)))
    for session in deleting_sessions:
        session.updated_at = current
    if deleting_sessions:
        db.commit()
    for session in deleting_sessions:
        try: enqueue_tutor_session_deletion(settings, session.id)
        except Exception: logger.exception("tutor_session_cleanup_reconcile_failed session_id=%s", session.id)

    deletion_jobs = list(db.scalars(select(WorkspaceDeletionJob).where(
        ((WorkspaceDeletionJob.status == "running") & WorkspaceDeletionJob.lease_expires_at.is_not(None) & (WorkspaceDeletionJob.lease_expires_at < current))
        | ((WorkspaceDeletionJob.status == "retry_wait") & WorkspaceDeletionJob.next_attempt_at.is_not(None) & (WorkspaceDeletionJob.next_attempt_at <= current))
        | ((WorkspaceDeletionJob.status == "queued") & (WorkspaceDeletionJob.updated_at < stale_before))
    ).with_for_update(skip_locked=True)))
    for job in deletion_jobs:
        job.status = "queued"; job.worker_id = None; job.lease_expires_at = None; job.heartbeat_at = None; job.next_attempt_at = None; job.updated_at = current
    db.commit()
    for job in deletion_jobs:
        try: enqueue_workspace_deletion_job(settings, job.id)
        except Exception:
            logger.exception("workspace_deletion_reconcile_enqueue_failed job_id=%s", job.id)
            job.status = "queue_failed"
            job.error_code = "queue_unavailable"
            job.error_message = "Workspace 删除队列暂时不可用，可稍后重试"
    if deletion_jobs:
        db.commit()

    if ingestion_jobs or stale_batches:
        logger.info("ingestion_reconciled recovered_jobs=%s reconciled_batches=%s", len(ingestion_jobs), stale_batches)
    return len(ingestion_jobs) + len(course_jobs) + len(canceled_course_jobs) + len(tutor_turns) + len(deleting_sessions) + len(deletion_jobs) + stale_batches

import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from learn_platform_api.db.models import AgentRun, PracticeAttempt, PracticeJob
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.practice_generation import execute_generation, execute_grading
from learn_platform_api.services.practice import cleanup_set
from learn_platform_api.settings import get_settings


logger = logging.getLogger(__name__)

RETRYABLE_CODES = {"provider_unavailable", "invalid_practice_artifact"}

ERROR_MESSAGES = {
    "source_snapshot_stale": "课程来源已变化，请基于当前资料重新生成",
    "provider_unconfigured": "练习模型尚未配置",
    "provider_unavailable": "练习模型服务暂不可用",
    "insufficient_evidence": "当前资料不足以生成练习",
    "invalid_practice_artifact": "练习结果未通过结构或引用校验",
    "invalid_rubric": "评分标准未通过校验",
    "unknown_citation": "引用校验失败",
    "answer_too_large": "简答答案超出长度限制",
    "generation_budget_exceeded": "练习生成达到运行预算，未提交截断结果",
    "grading_budget_exceeded": "评分达到运行预算，未提交结果",
    "practice_budget_exceeded": "练习生成达到受控预算",
    "practice_canceled": "练习任务已取消",
    "queue_unavailable": "练习队列暂时不可用",
}


def heartbeat_practice_job(job_id: str, worker_id: str, settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(update(PracticeJob).where(PracticeJob.id == job_id, PracticeJob.status == "running", PracticeJob.worker_id == worker_id).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds))).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_practice_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()

    def loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_practice_job(job_id, worker_id, settings):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=loop, name=f"practice-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=5)


def _capture_progress(db, job: PracticeJob) -> int:
    """Read the authoritative step_count from the in-progress AgentRun.

    The run's step_count is updated incrementally during execution (before each
    provider call and each search), so even a mid-flight failure reflects the
    real number of attempted steps. ToolCall count is a consistency lower bound
    only (plan is not a ToolCall). The session may be autoflush-disabled, so we
    flush here to make the updated step_count readable.
    """
    try:
        db.flush()
    except Exception:
        return 0
    run = db.scalar(select(AgentRun).where(AgentRun.practice_job_id == job.id, AgentRun.workspace_id == job.workspace_id, AgentRun.status == "running"))
    if run is None:
        return 0
    return run.step_count or 0


def _fail_job(db, job: PracticeJob, code: str, *, retryable: bool, settings, step_count: int = 0) -> None:
    role = "exercise_author" if job.job_type == "generate_set" else "answer_grader"
    db.add(AgentRun(practice_job_id=job.id, workspace_id=job.workspace_id, role=role, attempt_number=job.attempt_count, status="failed", step_count=step_count, error_code=code, completed_at=datetime.now(timezone.utc)))
    if retryable and job.attempt_count < settings.ingestion_max_attempts:
        job.status = "retry_wait"
        job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        # Keep the attempt consistent with the retrying job; it must not keep
        # pretending to be plain "grading" while the job waits to retry.
        if job.job_type == "grade_attempt":
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            if attempt is not None and attempt.status not in {"succeeded", "canceled"}:
                attempt.status = "retry_wait"
                attempt.error_code = code
                attempt.error_message = ERROR_MESSAGES.get(code, "评分失败")
    else:
        job.status = "failed"
        job.next_attempt_at = None
        if job.job_type == "grade_attempt":
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            if attempt is not None and attempt.status not in {"succeeded", "canceled"}:
                attempt.status = "failed"
                attempt.error_code = code
                attempt.error_message = ERROR_MESSAGES.get(code, "评分失败")
    job.error_code = code
    job.error_message = ERROR_MESSAGES.get(code, "练习任务失败")
    job.lease_expires_at = None
    job.heartbeat_at = None


def run_practice_job(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        job = db.get(PracticeJob, job_id)
        if job is None:
            return
        current = datetime.now(timezone.utc)
        # claim only queued, or retry_wait whose backoff has elapsed.
        due = job.status == "queued" or (job.status == "retry_wait" and job.next_attempt_at is not None and job.next_attempt_at <= current)
        if not due:
            return
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        claimed = db.execute(update(PracticeJob).where(
            PracticeJob.id == job_id,
            (PracticeJob.status == "queued") | ((PracticeJob.status == "retry_wait") & PracticeJob.next_attempt_at.is_not(None) & (PracticeJob.next_attempt_at <= current)),
        ).values(status="running", attempt_count=PracticeJob.attempt_count + 1, worker_id=worker_id, heartbeat_at=current, lease_expires_at=current + timedelta(seconds=settings.ingestion_lease_seconds), next_attempt_at=None, error_code=None, error_message=None)).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(PracticeJob, job_id)
        try:
            with maintain_practice_lease(job.id, worker_id, settings) as lease_lost:
                if job.job_type == "generate_set":
                    execute_generation(db, settings, job, worker_id=worker_id, lease_lost=lease_lost)
                else:
                    execute_grading(db, settings, job, worker_id=worker_id, lease_lost=lease_lost)
                if lease_lost.is_set():
                    raise ValueError("practice_canceled")
            db.commit()
        except ValueError as exc:
            progress = _capture_progress(db, job)
            db.rollback()
            job = db.get(PracticeJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            if job.status == "cancel_requested":
                job.status = "canceled"
                job.error_code = "practice_canceled"
                job.error_message = ERROR_MESSAGES["practice_canceled"]
                job.worker_id = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.next_attempt_at = None
                job.completed_at = datetime.now(timezone.utc)
                if job.job_type == "grade_attempt":
                    attempt = db.get(PracticeAttempt, job.practice_attempt_id)
                    if attempt is not None and attempt.status not in {"succeeded"}:
                        attempt.status = "canceled"
                        attempt.completed_at = datetime.now(timezone.utc)
                db.commit()
                return
            if job.status != "running":
                return
            code = str(exc)
            _fail_job(db, job, code, retryable=code in RETRYABLE_CODES, settings=settings, step_count=progress)
            db.commit()
        except Exception:
            logger.exception("practice_internal_error job_id=%s", job_id)
            progress = _capture_progress(db, job)
            db.rollback()
            job = db.get(PracticeJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            if job.status == "cancel_requested":
                job.status = "canceled"
                job.error_code = "practice_canceled"
                job.error_message = ERROR_MESSAGES["practice_canceled"]
                job.worker_id = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.next_attempt_at = None
                job.completed_at = datetime.now(timezone.utc)
                if job.job_type == "grade_attempt":
                    attempt = db.get(PracticeAttempt, job.practice_attempt_id)
                    if attempt is not None and attempt.status != "succeeded":
                        attempt.status = "canceled"
                        attempt.completed_at = datetime.now(timezone.utc)
                db.commit()
                return
            if job.status != "running":
                return
            _fail_job(db, job, "practice_internal_error", retryable=False, settings=settings, step_count=progress)
            db.commit()


def cleanup_practice_set(set_id: str) -> None:
    with SessionLocal() as db:
        cleanup_set(db, set_id)

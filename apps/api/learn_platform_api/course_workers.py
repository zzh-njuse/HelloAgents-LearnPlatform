import socket
import threading
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from learn_platform_api.db.session import SessionLocal
from learn_platform_api.db.models import AgentRun, CourseGenerationJob
from learn_platform_api.services.course_generation import execute_generation
from learn_platform_api.settings import get_settings


logger = logging.getLogger(__name__)


def heartbeat_course_job(job_id: str, worker_id: str, settings) -> bool:
    now = datetime.now(timezone.utc)
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(update(CourseGenerationJob).where(CourseGenerationJob.id == job_id, CourseGenerationJob.status == "running", CourseGenerationJob.worker_id == worker_id).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds))).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_course_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lost = threading.Event()
    def loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_course_job(job_id, worker_id, settings):
                    lost.set(); return
            except Exception:
                lost.set(); return
    thread = threading.Thread(target=loop, name=f"course-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set(); thread.join(timeout=5)


def run_course_generation_job(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        job = db.get(CourseGenerationJob, job_id)
        if job is None or job.status not in {"queued", "retry_wait"}:
            return
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        now = datetime.now(timezone.utc)
        claimed = db.execute(update(CourseGenerationJob).where(CourseGenerationJob.id == job_id, CourseGenerationJob.status.in_({"queued", "retry_wait"})).values(status="running", attempt_count=CourseGenerationJob.attempt_count + 1, worker_id=worker_id, heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds), next_attempt_at=None, error_code=None, error_message=None)).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(CourseGenerationJob, job_id)
        try:
            with maintain_course_lease(job.id, worker_id, settings) as lease_lost:
                execute_generation(db, settings, job)
                if lease_lost.is_set():
                    raise ValueError("generation_canceled")
            db.commit()
        except ValueError as exc:
            db.rollback()
            job = db.get(CourseGenerationJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            if job.status == "cancel_requested":
                job.status = "canceled"
                job.error_code = "generation_canceled"
                job.error_message = "课程生成已取消"
                job.worker_id = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.next_attempt_at = None
                db.commit()
                return
            if job.status != "running":
                return
            code = str(exc)
            run = db.scalar(select(AgentRun).where(
                AgentRun.course_generation_job_id == job.id,
                AgentRun.attempt_number == job.attempt_count,
                AgentRun.status == "running",
            ).order_by(AgentRun.created_at.desc()))
            if run is None:
                run = AgentRun(course_generation_job_id=job.id, workspace_id=job.workspace_id, role="course_architect" if job.job_type == "course_outline" else "lesson_writer", attempt_number=job.attempt_count, status="failed", step_count=0)
                db.add(run)
            run.status = "failed"
            run.error_code = code
            run.completed_at = datetime.now(timezone.utc)
            retryable = code in {"generation_provider_unavailable", "invalid_agent_artifact", "lesson_coverage_invalid"} and job.attempt_count < settings.ingestion_max_attempts
            job.status = "retry_wait" if retryable else ("canceled" if code == "generation_canceled" else "failed")
            job.error_code = code
            job.error_message = {
                "source_snapshot_stale": "课程来源已变化，请基于当前资料重新生成",
                "generation_provider_unconfigured": "课程生成模型尚未配置",
                "generation_provider_unavailable": "课程生成服务暂不可用",
                "insufficient_evidence": "当前资料不足以生成内容",
                "invalid_agent_artifact": "生成结果未通过结构或引用校验",
                "agent_step_budget_exceeded": "课程生成超过受控步骤预算",
                "lesson_coverage_invalid": "课节覆盖计划无效，请重试",
                "lesson_evidence_insufficient": "当前资料不足以完整讲解这个课节",
                "lesson_budget_exceeded": "课节生成达到运行预算，未提交截断草稿",
                "lesson_coverage_incomplete": "课节内容复核后仍有核心缺口，请重试",
                "generation_canceled": "课程生成已取消",
            }.get(code, "课程生成失败")
            job.lease_expires_at = None
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=5) if retryable else None
            db.commit()
        except Exception:
            logger.exception("course_generation_internal_error job_id=%s", job_id)
            db.rollback()
            job = db.get(CourseGenerationJob, job_id)
            if not job or job.worker_id != worker_id:
                return
            if job.status == "cancel_requested":
                job.status = "canceled"
                job.error_code = "generation_canceled"
                job.error_message = "课程生成已取消"
                job.worker_id = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.next_attempt_at = None
                db.commit()
                return
            if job.status != "running":
                return
            db.add(AgentRun(course_generation_job_id=job.id, workspace_id=job.workspace_id, role="course_architect" if job.job_type == "course_outline" else "lesson_writer", attempt_number=job.attempt_count, status="failed", step_count=0, error_code="generation_internal_error", completed_at=datetime.now(timezone.utc)))
            job.status = "failed"
            job.error_code = "generation_internal_error"
            job.error_message = "课程生成内部错误"
            job.lease_expires_at = None
            job.next_attempt_at = None
            db.commit()

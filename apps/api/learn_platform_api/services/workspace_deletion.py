import logging
from datetime import datetime, timezone

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun, AgentToolCall, Course, CourseGenerationJob, CourseGenerationJobSource,
    CourseSection, CourseSectionCitation, CourseVersion, CourseVersionSource,
    DocumentChunk, DocumentParseReport, DocumentVersion, IngestionBatch,
    IngestionBatchItem, IngestionJob, Lesson, LessonCitation, LessonVersion,
    RagAnswerTrace, RagQueryTrace, SourceDocument, TutorSession, TutorTurn,
    TutorTurnCitation, Workspace, WorkspaceDeletionJob,
)
from learn_platform_api.services.queue import enqueue_workspace_deletion_job
from learn_platform_api.services.storage import remove_tree
from learn_platform_api.settings import Settings


logger = logging.getLogger("learn_platform_api.workspace_deletion")
ACTIVE_JOB_STATUSES = {"queued", "running", "retry_wait", "cancel_requested"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def deletion_impact(db: Session, workspace_id: str) -> dict[str, int] | None:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active"))
    if workspace is None:
        return None
    ingestion = db.scalar(select(func.count()).select_from(IngestionJob).where(IngestionJob.workspace_id == workspace_id, IngestionJob.status.in_(ACTIVE_JOB_STATUSES))) or 0
    courses = db.scalar(select(func.count()).select_from(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id, CourseGenerationJob.status.in_(ACTIVE_JOB_STATUSES))) or 0
    tutors = db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.workspace_id == workspace_id, TutorTurn.status.in_(ACTIVE_JOB_STATUSES))) or 0
    return {
        "document_count": db.scalar(select(func.count()).select_from(SourceDocument).where(SourceDocument.workspace_id == workspace_id)) or 0,
        "course_count": db.scalar(select(func.count()).select_from(Course).where(Course.workspace_id == workspace_id)) or 0,
        "active_job_count": ingestion + courses + tutors,
        "tutor_session_count": db.scalar(select(func.count()).select_from(TutorSession).where(TutorSession.workspace_id == workspace_id)) or 0,
    }


def create_deletion(
    db: Session, settings: Settings, workspace_id: str, confirmation_name: str, idempotency_key: str
) -> WorkspaceDeletionJob:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    if workspace is None:
        raise LookupError("workspace_not_found")
    if confirmation_name != workspace.name:
        raise ValueError("confirmation_mismatch")
    existing = db.scalar(
        select(WorkspaceDeletionJob)
        .where(WorkspaceDeletionJob.workspace_id == workspace_id, WorkspaceDeletionJob.status.in_({"queued", "running", "retry_wait"}))
        .order_by(WorkspaceDeletionJob.created_at.desc())
    )
    if workspace.lifecycle_status == "deleting":
        if existing:
            return existing
        raise ValueError("workspace_deleting")
    if workspace.lifecycle_status != "active":
        raise LookupError("workspace_not_found")

    workspace.lifecycle_status = "deleting"
    workspace.deleted_at = now()
    db.execute(update(IngestionJob).where(IngestionJob.workspace_id == workspace_id, IngestionJob.status.in_(ACTIVE_JOB_STATUSES)).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None))
    db.execute(update(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id, CourseGenerationJob.status.in_(ACTIVE_JOB_STATUSES)).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None))
    db.execute(update(TutorTurn).where(TutorTurn.workspace_id == workspace_id, TutorTurn.status.in_(ACTIVE_JOB_STATUSES)).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None))
    db.execute(update(IngestionBatchItem).where(IngestionBatchItem.batch_id.in_(select(IngestionBatch.id).where(IngestionBatch.workspace_id == workspace_id)), IngestionBatchItem.status.in_({"pending", "queued", "processing"})).values(status="cancel_requested"))
    job = WorkspaceDeletionJob(workspace_id=workspace_id, status="queued", idempotency_key=idempotency_key)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        enqueue_workspace_deletion_job(settings, job.id)
    except Exception:
        logger.exception("workspace_deletion_enqueue_failed job_id=%s", job.id)
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "Workspace 删除队列暂时不可用，可稍后重试"
        db.commit()
    return job


def get_deletion_job(db: Session, job_id: str) -> WorkspaceDeletionJob | None:
    return db.get(WorkspaceDeletionJob, job_id)


def retry_deletion(db: Session, settings: Settings, job_id: str) -> WorkspaceDeletionJob | None:
    job = db.scalar(select(WorkspaceDeletionJob).where(WorkspaceDeletionJob.id == job_id).with_for_update())
    if job is None:
        return None
    if job.status not in {"failed", "queue_failed"}:
        raise ValueError("deletion_not_retryable")
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None or workspace.lifecycle_status != "deleting":
        raise ValueError("workspace_not_deleting")
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.next_attempt_at = None
    db.commit()
    try:
        enqueue_workspace_deletion_job(settings, job.id)
    except Exception:
        logger.exception("workspace_deletion_retry_enqueue_failed job_id=%s", job.id)
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "Workspace 删除队列暂时不可用，可稍后重试"
        db.commit()
    return job


def _delete_qdrant(settings: Settings, workspace_id: str) -> None:
    client = QdrantClient(url=settings.qdrant_url)
    try:
        if client.collection_exists(settings.product_collection_name):
            client.delete(
                settings.product_collection_name,
                points_selector=FilterSelector(filter=Filter(must=[FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))])),
                wait=True,
            )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _delete_database_rows(db: Session, workspace_id: str) -> None:
    run_ids = select(AgentRun.id).where(AgentRun.workspace_id == workspace_id)
    batch_ids = select(IngestionBatch.id).where(IngestionBatch.workspace_id == workspace_id)
    document_ids = select(SourceDocument.id).where(SourceDocument.workspace_id == workspace_id)
    version_ids = select(DocumentVersion.id).where(DocumentVersion.document_id.in_(document_ids))

    db.execute(update(SourceDocument).where(SourceDocument.workspace_id == workspace_id).values(current_version_id=None))
    db.execute(update(Course).where(Course.workspace_id == workspace_id).values(current_active_version_id=None))
    db.execute(update(Lesson).where(Lesson.workspace_id == workspace_id).values(current_published_version_id=None))

    db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
    db.execute(delete(AgentRun).where(AgentRun.workspace_id == workspace_id))
    db.execute(delete(TutorTurnCitation).where(TutorTurnCitation.workspace_id == workspace_id))
    db.execute(delete(TutorTurn).where(TutorTurn.workspace_id == workspace_id))
    db.execute(delete(TutorSession).where(TutorSession.workspace_id == workspace_id))
    db.execute(delete(LessonCitation).where(LessonCitation.workspace_id == workspace_id))
    db.execute(delete(CourseSectionCitation).where(CourseSectionCitation.workspace_id == workspace_id))
    db.execute(delete(CourseGenerationJobSource).where(CourseGenerationJobSource.workspace_id == workspace_id))
    db.execute(delete(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id))
    db.execute(delete(LessonVersion).where(LessonVersion.workspace_id == workspace_id))
    db.execute(delete(Lesson).where(Lesson.workspace_id == workspace_id))
    db.execute(delete(CourseSection).where(CourseSection.workspace_id == workspace_id))
    db.execute(delete(CourseVersionSource).where(CourseVersionSource.workspace_id == workspace_id))
    db.execute(delete(CourseVersion).where(CourseVersion.workspace_id == workspace_id))
    db.execute(delete(Course).where(Course.workspace_id == workspace_id))

    db.execute(delete(RagAnswerTrace).where(RagAnswerTrace.workspace_id == workspace_id))
    db.execute(delete(RagQueryTrace).where(RagQueryTrace.workspace_id == workspace_id))
    db.execute(delete(IngestionBatchItem).where(IngestionBatchItem.batch_id.in_(batch_ids)))
    db.execute(delete(IngestionBatch).where(IngestionBatch.workspace_id == workspace_id))
    db.execute(delete(DocumentParseReport).where(DocumentParseReport.document_version_id.in_(version_ids)))
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id.in_(version_ids)))
    db.execute(delete(IngestionJob).where(IngestionJob.workspace_id == workspace_id))
    db.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids)))
    db.execute(delete(SourceDocument).where(SourceDocument.workspace_id == workspace_id))
    db.execute(delete(Workspace).where(Workspace.id == workspace_id, Workspace.lifecycle_status == "deleting"))


def execute_deletion(db: Session, settings: Settings, job: WorkspaceDeletionJob) -> None:
    workspace = db.scalar(select(Workspace).where(Workspace.id == job.workspace_id).with_for_update())
    if workspace is None:
        job.status = "succeeded"
        job.completed_at = now()
        return
    if workspace.lifecycle_status != "deleting":
        raise ValueError("workspace_not_deleting")
    # Holding the workspace row lock serializes against workers' final commit checks.
    _delete_qdrant(settings, job.workspace_id)
    remove_tree(settings.storage_root, f"workspaces/{job.workspace_id}")
    _delete_database_rows(db, job.workspace_id)
    job.status = "succeeded"
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.error_code = None
    job.error_message = None
    job.completed_at = now()

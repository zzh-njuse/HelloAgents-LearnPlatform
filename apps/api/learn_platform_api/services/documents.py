import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from learn_platform_api.db.models import DocumentVersion, IngestionJob, SourceDocument, Workspace
from learn_platform_api.services.queue import enqueue_ingestion_job
from learn_platform_api.services.storage import remove_file, safe_extension, write_original
from learn_platform_api.settings import Settings


CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}
logger = logging.getLogger("learn_platform_api.documents")


def safe_display_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not name
        or len(name) > 255
        or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in name)
    ):
        raise ValueError("invalid_filename")
    return name


def validate_content(extension: str, content: bytes) -> None:
    if extension == ".pdf":
        if b"%PDF-" not in content[:1024]:
            raise ValueError("invalid_file_content")
        return
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid_file_content") from exc


def document_summary(db: Session, document: SourceDocument) -> dict[str, object]:
    version = db.get(DocumentVersion, document.current_version_id) if document.current_version_id else db.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number.desc())
    )
    job = db.scalar(
        select(IngestionJob).where(IngestionJob.document_version_id == version.id).order_by(IngestionJob.updated_at.desc())
    ) if version else None
    return {
        "id": document.id,
        "workspace_id": document.workspace_id,
        "display_name": document.display_name,
        "lifecycle_status": document.lifecycle_status,
        "current_version_id": document.current_version_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "current_version": version,
        "latest_job": job,
    }


def list_documents(db: Session, workspace_id: str) -> list[dict[str, object]]:
    documents = list(
        db.execute(
            select(SourceDocument)
            .where(SourceDocument.workspace_id == workspace_id, SourceDocument.lifecycle_status == "active")
            .order_by(SourceDocument.created_at.desc())
        ).scalars()
    )
    return [document_summary(db, document) for document in documents]


def get_document(db: Session, workspace_id: str, document_id: str) -> SourceDocument | None:
    return db.scalar(
        select(SourceDocument).where(
            SourceDocument.id == document_id,
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.lifecycle_status == "active",
        )
    )


def create_document(
    db: Session, settings: Settings, workspace_id: str, filename: str, content_type: str | None, content: bytes
) -> tuple[SourceDocument, DocumentVersion, IngestionJob]:
    if db.get(Workspace, workspace_id) is None:
        raise LookupError("workspace_not_found")
    extension = safe_extension(filename)
    if not extension or content_type not in {None, CONTENT_TYPES[extension], "application/octet-stream"}:
        raise ValueError("unsupported_type")
    if not content:
        raise ValueError("empty_file")
    if len(content) > settings.document_max_bytes:
        raise ValueError("file_too_large")
    display_name = safe_display_name(filename)
    validate_content(extension, content)

    document = SourceDocument(workspace_id=workspace_id, display_name=display_name)
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        processing_status="queued",
        original_filename=display_name,
        mime_type=CONTENT_TYPES[extension],
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        original_storage_uri=f"workspaces/{workspace_id}/documents/{document.id}/versions/{{version_id}}/original{extension}",
    )
    db.add(version)
    db.flush()
    version.original_storage_uri = version.original_storage_uri.format(version_id=version.id)
    job = IngestionJob(
        workspace_id=workspace_id,
        document_version_id=version.id,
        job_type="ingest_document_version",
        status="queued",
        idempotency_key=f"ingest_document_version:{version.id}:1",
    )
    db.add(job)
    original_written = False
    try:
        write_original(settings.storage_root, version.original_storage_uri, content)
        original_written = True
        db.commit()
    except Exception:
        db.rollback()
        if original_written:
            try:
                remove_file(settings.storage_root, version.original_storage_uri)
            except Exception:
                logger.exception("document_original_cleanup_failed workspace_id=%s", workspace_id)
        raise
    db.refresh(document)
    db.refresh(version)
    db.refresh(job)
    try:
        enqueue_ingestion_job(settings, job.id)
    except Exception:
        logger.exception("document_enqueue_failed job_id=%s", job.id)
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "任务队列暂不可用，可稍后重试"
        db.commit()
        db.refresh(job)
    return document, version, job


def retry_job(db: Session, settings: Settings, workspace_id: str, job_id: str) -> IngestionJob | None:
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.workspace_id == workspace_id))
    if job is None:
        return None
    if job.status in {"queued", "running"}:
        return job
    if job.status not in {"failed", "queue_failed"}:
        raise ValueError("job_not_retryable")
    claimed = db.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job.id, IngestionJob.status.in_({"failed", "queue_failed"}))
        .values(status="queued", error_code=None, error_message=None, next_attempt_at=None)
    ).rowcount
    db.commit()
    if not claimed:
        db.refresh(job)
        return job
    try:
        enqueue_ingestion_job(settings, job.id)
    except Exception:
        logger.exception("document_retry_enqueue_failed job_id=%s", job.id)
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "任务队列暂不可用，可稍后重试"
        db.commit()
    db.refresh(job)
    return job


def delete_document(db: Session, settings: Settings, workspace_id: str, document_id: str) -> IngestionJob | None:
    document = db.scalar(
        select(SourceDocument)
        .where(
            SourceDocument.id == document_id,
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.lifecycle_status == "active",
        )
        .with_for_update()
    )
    if document is None:
        return None
    current_version_id = document.current_version_id or db.scalar(
        select(DocumentVersion.id).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number.desc())
    )
    document.lifecycle_status = "deleted"
    document.deleted_at = datetime.now(timezone.utc)
    document.current_version_id = None
    job = IngestionJob(
        workspace_id=workspace_id,
        document_version_id=current_version_id,
        job_type="cleanup_document",
        status="queued",
        idempotency_key=f"cleanup_document:{document.id}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        enqueue_ingestion_job(settings, job.id)
    except Exception:
        logger.exception("document_cleanup_enqueue_failed job_id=%s", job.id)
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "清理任务暂不可用，资料已从列表和检索中移除"
        db.commit()
        db.refresh(job)
    return job

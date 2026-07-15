import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import DocumentVersion, IngestionBatch, IngestionBatchItem, IngestionJob, Workspace
from learn_platform_api.services.documents import create_document, retry_job, safe_display_name
from learn_platform_api.settings import Settings
from learn_platform_api.services.workspaces import workspace_is_active


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_hash(files: list[tuple[str, str | None, bytes]]) -> str:
    payload = [
        {
            "name": filename,
            "type": content_type or "",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for filename, content_type, content in files
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _legacy_metadata_hash(files: list[tuple[str, str | None, bytes]]) -> str:
    payload = [
        {"name": filename, "type": content_type or "", "size": len(content)}
        for filename, content_type, content in files
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _error_message(code: str) -> str:
    return {
        "unsupported_type": "仅支持 PDF、Markdown 或 TXT",
        "empty_file": "文件不能为空",
        "file_too_large": "文件不能超过 25 MiB",
        "invalid_filename": "文件名无效",
        "invalid_file_content": "文件内容与格式不匹配或编码无效",
        "upload_interrupted": "上传在接收完成前中断，请重新提交该文件",
    }.get(code, "该文件未能接收，可检查后重新提交")


def _items(db: Session, batch_id: str) -> list[IngestionBatchItem]:
    return list(db.scalars(select(IngestionBatchItem).where(IngestionBatchItem.batch_id == batch_id).order_by(IngestionBatchItem.client_ordinal)))


def refresh_batch(db: Session, batch: IngestionBatch) -> IngestionBatch:
    items = _items(db, batch.id)
    terminal = True
    ready = failed = canceled = accepted = 0
    for item in items:
        if item.ingestion_job_id:
            job = db.get(IngestionJob, item.ingestion_job_id)
            version = db.get(DocumentVersion, item.document_version_id) if item.document_version_id else None
            if job:
                if job.status == "succeeded" and version and version.processing_status == "ready":
                    item.status = "ready"
                elif job.status in {"failed", "queue_failed"}:
                    item.status = "failed"
                    item.error_code = job.error_code
                    item.error_message = job.error_message
                elif job.status == "canceled":
                    item.status = "canceled"
                elif item.status != "cancel_requested":
                    item.status = "processing" if job.status == "running" else "queued"
        if item.status in {"accepted", "queued", "processing", "pending", "cancel_requested"}:
            terminal = False
        if item.status in {"accepted", "queued", "processing", "ready", "failed", "cancel_requested"}:
            accepted += 1
        ready += item.status == "ready"
        failed += item.status in {"failed", "rejected"}
        canceled += item.status == "canceled"
    batch.accepted_count = accepted
    batch.ready_count = ready
    batch.failed_count = failed
    batch.canceled_count = canceled
    if terminal:
        if ready == len(items) and items:
            batch.status = "completed"
        elif ready:
            batch.status = "partial_failed"
        elif canceled and not failed:
            batch.status = "canceled"
        else:
            batch.status = "failed"
        batch.completed_at = batch.completed_at or _now()
    elif batch.status != "cancel_requested":
        batch.status = "processing"
    db.commit()
    db.refresh(batch)
    return batch


def batch_read(db: Session, batch: IngestionBatch) -> dict[str, object]:
    batch = refresh_batch(db, batch)
    return {
        "id": batch.id,
        "workspace_id": batch.workspace_id,
        "status": batch.status,
        "item_count": batch.item_count,
        "accepted_count": batch.accepted_count,
        "ready_count": batch.ready_count,
        "failed_count": batch.failed_count,
        "canceled_count": batch.canceled_count,
        "total_declared_bytes": batch.total_declared_bytes,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "completed_at": batch.completed_at,
        "items": _items(db, batch.id),
    }


def create_batch(
    db: Session,
    settings: Settings,
    workspace_id: str,
    idempotency_key: str,
    files: list[tuple[str, str | None, bytes]],
) -> dict[str, object]:
    if not workspace_is_active(db, workspace_id):
        raise LookupError("workspace_not_found")
    if not files or len(files) > settings.batch_max_files:
        raise ValueError("batch_file_count_invalid")
    total_bytes = sum(len(content) for _, _, content in files)
    if total_bytes > settings.batch_max_bytes:
        raise ValueError("batch_too_large")
    request_hash = _request_hash(files)
    legacy_metadata_hash = _legacy_metadata_hash(files)
    existing = db.scalar(select(IngestionBatch).where(IngestionBatch.workspace_id == workspace_id, IngestionBatch.idempotency_key == idempotency_key))
    if existing:
        if existing.request_metadata_hash not in {request_hash, legacy_metadata_hash}:
            raise ValueError("idempotency_key_conflict")
        return batch_read(db, existing)
    batch = IngestionBatch(
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
        request_metadata_hash=request_hash,
        item_count=len(files),
        total_declared_bytes=total_bytes,
    )
    db.add(batch)
    try:
        # Flush is where PostgreSQL normally evaluates the unique constraint,
        # so the race must be handled here as well as at commit time.
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(IngestionBatch).where(
                IngestionBatch.workspace_id == workspace_id,
                IngestionBatch.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_metadata_hash not in {request_hash, legacy_metadata_hash}:
            raise ValueError("idempotency_key_conflict")
        return batch_read(db, existing)
    items = []
    for ordinal, (filename, content_type, content) in enumerate(files):
        try:
            display_name = safe_display_name(filename)
        except ValueError:
            display_name = "无效文件名"
        item = IngestionBatchItem(
            batch_id=batch.id,
            client_ordinal=ordinal,
            display_filename=display_name,
            declared_mime_type=content_type,
            declared_byte_size=len(content),
        )
        db.add(item)
        items.append(item)
    try:
        db.commit()
    except IntegrityError:
        # The composite unique constraint is the concurrency authority for an
        # Idempotency-Key race. Re-read the winning request after rollback.
        db.rollback()
        existing = db.scalar(
            select(IngestionBatch).where(
                IngestionBatch.workspace_id == workspace_id,
                IngestionBatch.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_metadata_hash not in {request_hash, legacy_metadata_hash}:
            raise ValueError("idempotency_key_conflict")
        return batch_read(db, existing)
    for item, (filename, content_type, content) in zip(items, files):
        try:
            document, version, job = create_document(db, settings, workspace_id, filename, content_type, content)
            item.document_id = document.id
            item.document_version_id = version.id
            item.ingestion_job_id = job.id
            item.status = "queued" if job.status in {"queued", "queue_failed"} else "processing"
            if job.status == "queue_failed":
                item.status = "failed"
                item.error_code = job.error_code
                item.error_message = job.error_message
        except ValueError as exc:
            item.status = "rejected"
            item.error_code = str(exc)
            item.error_message = _error_message(str(exc))
        except Exception:
            item.status = "failed"
            item.error_code = "batch_item_accept_failed"
            item.error_message = "文件接收失败，可重新提交该文件"
        db.commit()
    return batch_read(db, batch)


def get_batch(db: Session, workspace_id: str, batch_id: str) -> dict[str, object] | None:
    batch = db.scalar(select(IngestionBatch).where(IngestionBatch.id == batch_id, IngestionBatch.workspace_id == workspace_id))
    return batch_read(db, batch) if batch else None


def retry_batch(db: Session, settings: Settings, workspace_id: str, batch_id: str) -> dict[str, object] | None:
    batch = db.scalar(select(IngestionBatch).where(IngestionBatch.id == batch_id, IngestionBatch.workspace_id == workspace_id))
    if batch is None:
        return None
    for item in _items(db, batch.id):
        if item.ingestion_job_id:
            try:
                retry_job(db, settings, workspace_id, item.ingestion_job_id)
            except ValueError:
                continue
    return batch_read(db, batch)


def cancel_batch(db: Session, workspace_id: str, batch_id: str) -> dict[str, object] | None:
    batch = db.scalar(select(IngestionBatch).where(IngestionBatch.id == batch_id, IngestionBatch.workspace_id == workspace_id).with_for_update())
    if batch is None:
        return None
    batch.status = "cancel_requested"
    for item in _items(db, batch.id):
        if item.status in {"ready", "failed", "rejected", "canceled"}:
            continue
        if item.ingestion_job_id:
            job = db.get(IngestionJob, item.ingestion_job_id)
            if job and job.status in {"queued", "retry_wait", "queue_failed"}:
                job.status = "canceled"
                job.lease_expires_at = None
                item.status = "canceled"
            else:
                item.status = "cancel_requested"
        else:
            item.status = "canceled"
    db.commit()
    return batch_read(db, batch)


def reconcile_stale_batches(db: Session, older_than: datetime) -> int:
    batches = list(db.scalars(select(IngestionBatch).where(IngestionBatch.status == "accepting", IngestionBatch.updated_at < older_than)))
    for batch in batches:
        for item in _items(db, batch.id):
            if item.status == "pending":
                item.status = "failed"
                item.error_code = "upload_interrupted"
                item.error_message = _error_message("upload_interrupted")
        refresh_batch(db, batch)
    return len(batches)

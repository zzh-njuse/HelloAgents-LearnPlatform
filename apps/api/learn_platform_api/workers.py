import hashlib
import io
import logging
import multiprocessing
import re
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
from sqlalchemy import delete, func, select, update

from learn_platform_api.db.models import DocumentChunk, DocumentParseReport, DocumentVersion, IngestionBatchItem, IngestionJob, SourceDocument, Workspace
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.queue import enqueue_ingestion_job
from learn_platform_api.services.storage import read_bytes, remove_file, remove_tree, write_parsed
from learn_platform_api.settings import get_settings


logger = logging.getLogger("learn_platform_api.ingestion")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character
        if character == "\n" or character == "\t" or (ord(character) >= 32 and not 0xD800 <= ord(character) <= 0xDFFF)
        else " "
        for character in normalized
    )
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _parse_pdf_content(content: bytes, max_pages: int, max_chars: int) -> tuple[str, str, int, list[str]]:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("encrypted_pdf")
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise ValueError("pdf_page_limit_exceeded")
        page_texts: list[str] = []
        char_count = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            char_count += len(page_text)
            if char_count > max_chars:
                raise ValueError("parsed_text_limit_exceeded")
            page_texts.append(page_text)
    except FileNotDecryptedError as exc:
        raise ValueError("encrypted_pdf") from exc
    except PdfReadError as exc:
        raise ValueError("invalid_pdf") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("pdf_parse_failed") from exc
    text = normalize_text("\n\n".join(page_texts))
    if len(text) > max_chars:
        raise ValueError("parsed_text_limit_exceeded")
    if len(text) < 10:
        raise ValueError("ocr_required")
    warnings = ["empty_pdf_pages"] if any(not value.strip() for value in page_texts) else []
    return text, "pypdf", page_count, warnings


def _parse_pdf_worker(content: bytes, max_pages: int, max_chars: int, queue) -> None:
    try:
        queue.put(("ok", _parse_pdf_content(content, max_pages, max_chars)))
    except ValueError as exc:
        queue.put(("error", str(exc)))
    except Exception:
        queue.put(("error", "parser_process_failed"))


def _parse_pdf_isolated(content: bytes, max_pages: int, max_chars: int, timeout_seconds: int) -> tuple[str, str, int, list[str]]:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(target=_parse_pdf_worker, args=(content, max_pages, max_chars, queue))
    process.start()
    try:
        status, payload = queue.get(timeout=timeout_seconds)
    except Exception as exc:
        process.terminate()
        process.join(timeout=5)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5)
            raise ValueError("parser_timeout") from exc
        raise ValueError("parser_process_failed") from exc
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        raise ValueError("parser_timeout")
    if status == "error":
        raise ValueError(str(payload))
    return payload


def parse_document(filename: str, content: bytes, settings=None) -> tuple[str, str, int | None, list[str]]:
    suffix = filename.rsplit(".", 1)[-1].lower()
    if suffix in {"md", "txt"}:
        text = normalize_text(content.decode("utf-8-sig"))
        if settings and len(text) > settings.parsed_text_max_chars:
            raise ValueError("parsed_text_limit_exceeded")
        return text, "text", None, []
    if suffix == "pdf":
        max_pages = settings.pdf_max_pages if settings else 1_000_000
        max_chars = settings.parsed_text_max_chars if settings else 10_000_000
        if settings:
            return _parse_pdf_isolated(content, max_pages, max_chars, settings.parser_timeout_seconds)
        return _parse_pdf_content(content, max_pages, max_chars)
    raise ValueError("unsupported_type")


def chunk_text(text: str, size: int = 800, overlap: int = 100, max_chunks: int | None = None) -> list[tuple[str, int, int]]:
    normalized = normalize_text(text)
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = max(normalized.rfind("\n\n", start, end), normalized.rfind("。", start, end), normalized.rfind("\n", start, end))
            if boundary > start + size // 2:
                end = boundary + 1
        item = normalized[start:end].strip()
        if item:
            item_start = normalized.find(item, start, end)
            chunks.append((item, item_start, item_start + len(item)))
            if max_chunks is not None and len(chunks) > max_chunks:
                raise ValueError("chunk_limit_exceeded")
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def heading_path_at(text: str, offset: int) -> str | None:
    headings: list[str | None] = [None] * 6
    for match in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text[: offset + 1]):
        level = len(match.group(1)) - 1
        headings[level] = match.group(2).strip()
        for index in range(level + 1, len(headings)):
            headings[index] = None
    path = [heading for heading in headings if heading]
    return " / ".join(path) if path else None


def heading_paths_for_chunks(text: str, chunks: list[tuple[str, int, int]]) -> list[str | None]:
    headings: list[str | None] = [None] * 6
    matches = iter(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    next_match = next(matches, None)
    paths: list[str | None] = []
    for _, start, end in chunks:
        while next_match is not None and next_match.start() <= max(start, end - 1):
            level = len(next_match.group(1)) - 1
            headings[level] = next_match.group(2).strip()
            for index in range(level + 1, len(headings)):
                headings[index] = None
            next_match = next(matches, None)
        path = [heading for heading in headings if heading]
        paths.append(" / ".join(path) if path else None)
    return paths


def embed_texts(settings, texts: list[str], text_type: str) -> list[list[float]]:
    if settings.product_embedding_provider != "dashscope" or not settings.product_embedding_api_key:
        raise RuntimeError("embedding_provider_unconfigured")
    vectors: list[list[float]] = []
    headers = {"Authorization": f"Bearer {settings.product_embedding_api_key}"}
    with httpx.Client(timeout=settings.product_embedding_timeout_seconds) as client:
        for offset in range(0, len(texts), 10):
            response = client.post(
                settings.product_embedding_base_url,
                headers=headers,
                json={
                    "model": settings.product_embedding_model,
                    "input": {"texts": texts[offset : offset + 10]},
                    "parameters": {"dimension": settings.product_embedding_dimension, "text_type": text_type, "output_type": "dense"},
                },
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("output", {}).get("embeddings", [])
            vectors.extend(item["embedding"] for item in items)
    if len(vectors) != len(texts) or any(len(vector) != settings.product_embedding_dimension for vector in vectors):
        raise RuntimeError("embedding_dimension_mismatch")
    return vectors


def ensure_collection(client: QdrantClient, settings) -> None:
    if not client.collection_exists(settings.product_collection_name):
        client.create_collection(settings.product_collection_name, vectors_config=VectorParams(size=settings.product_embedding_dimension, distance=Distance.COSINE))
        return
    vectors = client.get_collection(settings.product_collection_name).config.params.vectors
    if vectors.size != settings.product_embedding_dimension or vectors.distance != Distance.COSINE:
        raise RuntimeError("collection_contract_mismatch")


def close_qdrant_client(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.warning("qdrant_client_close_failed exception_type=%s", type(client).__name__)


def heartbeat_job(job_id: str, worker_id: str, settings) -> bool:
    now = utc_now()
    with SessionLocal() as heartbeat_db:
        updated = heartbeat_db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.status == "running",
                IngestionJob.worker_id == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds),
            )
        ).rowcount
        heartbeat_db.commit()
        return bool(updated)


@contextmanager
def maintain_lease(job_id: str, worker_id: str, settings):
    stopped = threading.Event()
    lease_lost = threading.Event()

    def heartbeat_loop() -> None:
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                owned = heartbeat_job(job_id, worker_id, settings)
            except Exception:
                logger.exception("job_heartbeat_failed job_id=%s", job_id)
                owned = False
            if not owned:
                lease_lost.set()
                return

    thread = threading.Thread(target=heartbeat_loop, name=f"job-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield lease_lost
    finally:
        stopped.set()
        thread.join(timeout=1)


def ensure_job_owned(db, job: IngestionJob, worker_id: str, lease_lost: threading.Event | None = None) -> None:
    if lease_lost and lease_lost.is_set():
        raise RuntimeError("job_lease_lost")
    db.refresh(job)
    if job.status != "running" or job.worker_id != worker_id:
        raise RuntimeError("job_lease_lost")


def stable_error_code(exc: Exception) -> str:
    code = str(exc)
    if code in {"ocr_required", "encrypted_pdf", "invalid_pdf", "pdf_parse_failed", "no_extractable_text", "unsupported_type", "pdf_page_limit_exceeded", "parsed_text_limit_exceeded", "chunk_limit_exceeded", "embedding_input_limit_exceeded", "parser_timeout", "parser_process_failed", "batch_cancel_requested"}:
        return code
    if isinstance(exc, UnicodeDecodeError):
        return "invalid_text_encoding"
    if isinstance(exc, httpx.HTTPError):
        return "embedding_provider_unavailable"
    if isinstance(exc, (OSError, TimeoutError)):
        return "storage_or_network_unavailable"
    if exc.__class__.__module__.startswith("qdrant_client"):
        return "vector_store_unavailable"
    if code in {"embedding_provider_unconfigured", "embedding_dimension_mismatch", "collection_contract_mismatch", "job_lease_lost"}:
        return code
    return "ingestion_failed"


def ingestion_error_message(error_code: str, retryable: bool) -> str:
    if retryable:
        return "资料处理暂时失败，平台将自动重试"
    messages = {
        "ocr_required": "PDF 未检测到可用文本层，需要 OCR 扩展后才能导入",
        "encrypted_pdf": "PDF 已加密，当前无法读取文本层",
        "invalid_pdf": "PDF 文件结构无效，无法读取",
        "pdf_parse_failed": "PDF 文本层无法解析，可更换导出版本后重试",
        "invalid_text_encoding": "TXT 或 Markdown 不是有效的 UTF-8 文本",
        "pdf_page_limit_exceeded": "PDF 页数超过当前资料处理上限",
        "parsed_text_limit_exceeded": "解析后的文本量超过当前资料处理上限",
        "chunk_limit_exceeded": "资料切块数量超过当前处理上限",
        "embedding_input_limit_exceeded": "资料的向量化输入超过当前处理上限",
        "parser_timeout": "资料解析超时，可更换较小文件后重试",
        "parser_process_failed": "资料解析进程失败，可检查文件后重试",
    }
    return messages.get(error_code, "资料处理失败，可检查文件或重试")


def is_transient_error(exc: Exception) -> bool:
    return isinstance(exc, (httpx.HTTPError, OSError, TimeoutError)) or exc.__class__.__module__.startswith("qdrant_client")


def claim_job(db, job_id: str, worker_id: str, settings) -> IngestionJob | None:
    now = utc_now()
    current = db.get(IngestionJob, job_id)
    if current is None:
        return None
    workspace = db.scalar(select(Workspace).where(Workspace.id == current.workspace_id).with_for_update())
    if workspace is None:
        return None
    active = db.scalar(
        select(func.count()).select_from(IngestionJob).where(
            IngestionJob.workspace_id == current.workspace_id,
            IngestionJob.status == "running",
        )
    ) or 0
    if active >= settings.workspace_max_active_ingestions:
        return None
    claimed = db.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status.in_({"queued", "retry_wait"}))
        .values(
            status="running",
            attempt_count=IngestionJob.attempt_count + 1,
            worker_id=worker_id,
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds),
            next_attempt_at=None,
            error_code=None,
            error_message=None,
        )
    ).rowcount
    db.commit()
    return db.get(IngestionJob, job_id) if claimed else None


def is_batch_cancel_requested(db, job_id: str) -> bool:
    return bool(db.scalar(select(IngestionBatchItem.id).where(IngestionBatchItem.ingestion_job_id == job_id, IngestionBatchItem.status == "cancel_requested")))


def run_ingestion_job(job_id: str) -> None:
    settings = get_settings()
    db = None
    job = None
    worker_id: str | None = None
    client = None
    parsed_uri: str | None = None
    indexed_version_id: str | None = None
    phase = "startup"
    try:
        db = SessionLocal()
        phase = "load_job"
        job = db.get(IngestionJob, job_id)
        if job is None or job.status not in {"queued", "retry_wait"}:
            return
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job_id}"
        job = claim_job(db, job_id, worker_id, settings)
        if job is None:
            return
        if job.job_type == "cleanup_document":
            run_cleanup_job(db, settings, job, worker_id, claimed=True)
            return
        phase = "load_document"
        version = db.get(DocumentVersion, job.document_version_id)
        document = db.get(SourceDocument, version.document_id) if version else None
        if version is None or document is None:
            raise RuntimeError("document_not_found")
        if document.lifecycle_status != "active":
            job.status = "canceled"
            job.lease_expires_at = None
            db.commit()
            return
        if is_batch_cancel_requested(db, job.id):
            raise RuntimeError("batch_cancel_requested")
        version.processing_status = "processing"
        db.commit()
        with maintain_lease(job.id, worker_id, settings) as lease_lost:
            ensure_job_owned(db, job, worker_id, lease_lost)
            phase = "read_storage"
            content = read_bytes(settings.storage_root, version.original_storage_uri)
            phase = "parse"
            parsed, parser_key, page_count, warning_codes = parse_document(version.original_filename, content, settings)
            ensure_job_owned(db, job, worker_id, lease_lost)
            if is_batch_cancel_requested(db, job.id):
                raise RuntimeError("batch_cancel_requested")
            parsed_uri = f"workspaces/{job.workspace_id}/documents/{document.id}/versions/{version.id}/parsed/content.md"
            phase = "write_parsed"
            write_parsed(settings.storage_root, parsed_uri, parsed)
            phase = "chunk"
            chunks = chunk_text(parsed, max_chunks=settings.document_max_chunks)
            if not chunks:
                raise ValueError("no_extractable_text")
            chunk_headings = heading_paths_for_chunks(parsed, chunks)
            phase = "embed"
            if sum(max(1, int(len(item[0]) * 0.6)) for item in chunks) > settings.document_embedding_max_tokens:
                raise ValueError("embedding_input_limit_exceeded")
            ensure_job_owned(db, job, worker_id, lease_lost)
            vectors = embed_texts(settings, [item[0] for item in chunks], "document")
            phase = "verify_before_index"
            ensure_job_owned(db, job, worker_id, lease_lost)
            if is_batch_cancel_requested(db, job.id):
                raise RuntimeError("batch_cancel_requested")
            # Serialize final indexing with deletion. If delete owns this row first,
            # this worker observes the deleted lifecycle and never writes Qdrant.
            document = db.scalar(
                select(SourceDocument)
                .where(SourceDocument.id == document.id)
                .with_for_update()
            )
            if document is None:
                raise RuntimeError("document_not_found")
            if document.lifecycle_status != "active":
                raise RuntimeError("document_deleted")
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
            rows = []
            for ordinal, ((item, start, end), heading_path) in enumerate(zip(chunks, chunk_headings)):
                content_hash = hashlib.sha256(item.encode()).hexdigest()
                rows.append(DocumentChunk(id=str(uuid5(NAMESPACE_URL, f"{version.id}:{ordinal}:{content_hash}")), document_version_id=version.id, ordinal=ordinal, content=item, content_hash=content_hash, heading_path=heading_path, start_offset=start, end_offset=end))
            db.add_all(rows)
            db.flush()
            phase = "index"
            client = QdrantClient(url=settings.qdrant_url)
            ensure_collection(client, settings)
            client.upsert(settings.product_collection_name, [PointStruct(id=row.id, vector=vector, payload={"workspace_id": job.workspace_id, "document_id": document.id, "document_version_id": version.id, "chunk_id": row.id, "heading_path": row.heading_path, "content_hash": row.content_hash, "schema_version": 1}) for row, vector in zip(rows, vectors)], wait=True)
            indexed_version_id = version.id
            ensure_job_owned(db, job, worker_id, lease_lost)
            phase = "commit"
            version.processing_status = "ready"
            version.parsed_storage_uri = parsed_uri
            version.parser_key = parser_key
            version.parser_version = "1"
            version.embedding_model = settings.product_embedding_model
            version.embedding_dimension = settings.product_embedding_dimension
            version.ready_at = utc_now()
            document.current_version_id = version.id
            job.status = "succeeded"
            job.lease_expires_at = None
            job.next_attempt_at = None
            db.add(DocumentParseReport(document_version_id=version.id, attempt_number=job.attempt_count, parser_key=parser_key, parser_version="1", page_count=page_count, character_count=len(parsed), warning_codes=warning_codes))
            db.commit()
    except Exception as exc:
        if db is not None and job is not None:
            db.rollback()
            job = db.get(IngestionJob, job_id)
            version = db.get(DocumentVersion, job.document_version_id) if job and job.document_version_id else None
            if job is None:
                return
            if worker_id is not None and (job.status != "running" or job.worker_id != worker_id):
                return
            if indexed_version_id and client is not None:
                try:
                    client.delete(
                        settings.product_collection_name,
                        points_selector=Filter(
                            must=[FieldCondition(key="document_version_id", match=MatchValue(value=indexed_version_id))]
                        ),
                        wait=True,
                    )
                except Exception:
                    logger.exception("failed_ingestion_vector_cleanup job_id=%s", job_id)
            if parsed_uri:
                try:
                    remove_file(settings.storage_root, parsed_uri)
                except Exception:
                    logger.exception("failed_ingestion_parsed_cleanup job_id=%s", job_id)
            failed_document = db.get(SourceDocument, version.document_id) if version else None
            if failed_document is not None and failed_document.lifecycle_status != "active":
                job.status = "canceled"
                job.lease_expires_at = None
                job.error_code = None
                job.error_message = None
                if version is not None:
                    version.processing_status = "failed"
                db.commit()
                return
            error_code = stable_error_code(exc)
            logger.warning(
                "ingestion_job_failed job_id=%s phase=%s error_code=%s exception_type=%s",
                job_id,
                phase,
                error_code,
                type(exc).__name__,
            )
            if str(exc) in {"document_deleted", "batch_cancel_requested"}:
                job.status = "canceled"
                job.lease_expires_at = None
                job.error_code = "batch_canceled" if str(exc) == "batch_cancel_requested" else None
                job.error_message = "批次已取消" if str(exc) == "batch_cancel_requested" else None
                if version is not None:
                    version.processing_status = "failed"
                db.commit()
                return
            retryable = is_transient_error(exc) and job.attempt_count < settings.ingestion_max_attempts
            delay_seconds = min(60, 5 * (2 ** max(0, job.attempt_count - 1)))
            job.status = "retry_wait" if retryable else "failed"
            job.lease_expires_at = None
            job.error_code = error_code
            job.error_message = ingestion_error_message(error_code, retryable)
            job.next_attempt_at = utc_now() + timedelta(seconds=delay_seconds) if retryable else None
            if version is not None:
                version.processing_status = "queued" if retryable else "failed"
                db.add(DocumentParseReport(
                    document_version_id=version.id,
                    attempt_number=job.attempt_count,
                    error_code=job.error_code,
                    error_message=job.error_message,
                ))
            db.commit()
            if retryable:
                try:
                    enqueue_ingestion_job(settings, job.id, delay_seconds=delay_seconds)
                except Exception:
                    job.status = "queue_failed"
                    job.error_code = "queue_unavailable"
                    job.error_message = "任务队列暂不可用，可稍后重试"
                    db.commit()
    finally:
        if client is not None:
            close_qdrant_client(client)
        if db is not None:
            db.close()


def run_cleanup_job(db, settings, job: IngestionJob, worker_id: str | None = None, claimed: bool = False) -> None:
    client = None
    if not claimed:
        job.status = "running"
        job.attempt_count += 1
        worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{job.id}"
        job.worker_id = worker_id
        job.heartbeat_at = utc_now()
        job.lease_expires_at = utc_now() + timedelta(seconds=settings.ingestion_lease_seconds)
        db.commit()
    worker_id = worker_id or job.worker_id or ""
    try:
        version = db.get(DocumentVersion, job.document_version_id) if job.document_version_id else None
        document = db.scalar(
            select(SourceDocument)
            .where(SourceDocument.id == version.document_id)
            .with_for_update()
        ) if version else None
        if document is None:
            raise RuntimeError("cleanup_document_not_found")
        with maintain_lease(job.id, worker_id, settings) as lease_lost:
            ensure_job_owned(db, job, worker_id, lease_lost)
            client = QdrantClient(url=settings.qdrant_url)
            if client.collection_exists(settings.product_collection_name):
                client.delete(
                    settings.product_collection_name,
                    points_selector=Filter(
                        must=[FieldCondition(key="document_id", match=MatchValue(value=document.id))]
                    ),
                    wait=True,
                )
            remove_tree(settings.storage_root, f"workspaces/{job.workspace_id}/documents/{document.id}")
            ensure_job_owned(db, job, worker_id, lease_lost)
            job.status = "succeeded"
            job.lease_expires_at = None
            job.next_attempt_at = None
            job.error_code = None
            job.error_message = None
            db.commit()
            close_qdrant_client(client)
            client = None
    except Exception as exc:
        if client is not None:
            close_qdrant_client(client)
            client = None
        db.rollback()
        job = db.get(IngestionJob, job.id)
        if job is None:
            return
        if job.status != "running" or job.worker_id != worker_id:
            return
        retryable = is_transient_error(exc) and job.attempt_count < settings.ingestion_max_attempts
        delay_seconds = min(60, 5 * (2 ** max(0, job.attempt_count - 1)))
        job.status = "retry_wait" if retryable else "failed"
        job.lease_expires_at = None
        job.error_code = stable_error_code(exc)
        job.error_message = "资料已删除，平台将自动重试后台清理" if retryable else "资料已删除，但后台清理失败，可稍后重试"
        job.next_attempt_at = utc_now() + timedelta(seconds=delay_seconds) if retryable else None
        db.commit()
        if retryable:
            try:
                enqueue_ingestion_job(settings, job.id, delay_seconds=delay_seconds)
            except Exception:
                job.status = "queue_failed"
                job.error_code = "queue_unavailable"
                job.error_message = "清理队列暂不可用，资料仍保持删除状态"
                db.commit()

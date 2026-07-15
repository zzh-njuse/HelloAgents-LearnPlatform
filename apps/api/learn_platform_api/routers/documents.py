import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from learn_platform_api.db.session import get_db
from learn_platform_api.db.models import IngestionJob, Workspace
from learn_platform_api.schemas.documents import AnswerRequest, AnswerResponse, DocumentSummaryRead, DocumentUploadRead, IngestionBatchRead, IngestionJobRead, RetrievalQuery, RetrievalResponse
from learn_platform_api.services.answers import answer_question
from learn_platform_api.services.batches import cancel_batch, create_batch, get_batch, retry_batch
from learn_platform_api.services.documents import create_document, delete_document, document_course_impact, document_summary, get_document, list_documents, retry_job
from learn_platform_api.services.retrieval import retrieve
from learn_platform_api.services.workspaces import workspace_is_active
from learn_platform_api.settings import get_settings


logger = logging.getLogger("learn_platform_api.documents_router")


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["documents"])


@router.get("/documents", response_model=list[DocumentSummaryRead])
def list_documents_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return list_documents(db, workspace_id)


@router.post("/documents", response_model=DocumentUploadRead, status_code=status.HTTP_202_ACCEPTED)
async def upload_document_endpoint(
    workspace_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    content = await file.read(get_settings().document_max_bytes + 1)
    try:
        document, version, job = create_document(db, get_settings(), workspace_id, file.filename or "upload", file.content_type, content)
        return {"document": document, "version": version, "job": job}
    except LookupError:
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    except ValueError as exc:
        details = {
            "unsupported_type": "仅支持 PDF、Markdown 或 TXT",
            "empty_file": "文件不能为空",
            "file_too_large": "文件不能超过 25 MiB",
            "invalid_filename": "文件名无效",
            "invalid_file_content": "文件内容与格式不匹配或编码无效",
        }
        raise HTTPException(status_code=422, detail=details.get(str(exc), "文件无效"))


@router.get("/documents/{document_id}", response_model=DocumentSummaryRead)
def get_document_endpoint(workspace_id: str, document_id: str, db: Session = Depends(get_db)):
    document = get_document(db, workspace_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return document_summary(db, document)


@router.delete("/documents/{document_id}", response_model=IngestionJobRead, status_code=status.HTTP_202_ACCEPTED)
def delete_document_endpoint(workspace_id: str, document_id: str, db: Session = Depends(get_db)):
    job = delete_document(db, get_settings(), workspace_id, document_id)
    if job is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return job


@router.get("/documents/{document_id}/course-impact")
def document_course_impact_endpoint(workspace_id: str, document_id: str, db: Session = Depends(get_db)):
    if get_document(db, workspace_id, document_id) is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return {"affected_course_count": document_course_impact(db, workspace_id, document_id)}


@router.post("/ingestion-jobs/{job_id}/retry", response_model=IngestionJobRead, status_code=status.HTTP_202_ACCEPTED)
def retry_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        job = retry_job(db, get_settings(), workspace_id, job_id)
    except ValueError:
        raise HTTPException(status_code=409, detail="当前任务不能重试")
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobRead)
def get_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.workspace_id == workspace_id))
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/document-batches", response_model=IngestionBatchRead, status_code=status.HTTP_202_ACCEPTED)
async def upload_document_batch_endpoint(
    workspace_id: str,
    files: list[UploadFile] = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="批量上传需要有效的 Idempotency-Key")
    if not files or len(files) > settings.batch_max_files:
        raise HTTPException(status_code=422, detail="单批最多上传 20 个文件")
    payloads: list[tuple[str, str | None, bytes]] = []
    total_bytes = 0
    for file in files:
        content = await file.read(settings.document_max_bytes + 1)
        total_bytes += len(content)
        if total_bytes > settings.batch_max_bytes:
            raise HTTPException(status_code=413, detail="单批文件总大小不能超过 100 MiB")
        payloads.append((file.filename or "upload", file.content_type, content))
    try:
        return create_batch(db, settings, workspace_id, idempotency_key, payloads)
    except ValueError as exc:
        details = {
            "batch_file_count_invalid": "单批最多上传 20 个文件",
            "batch_too_large": "单批文件总大小不能超过 100 MiB",
            "idempotency_key_conflict": "同一 Idempotency-Key 不能用于不同文件批次",
        }
        raise HTTPException(status_code=409 if str(exc) == "idempotency_key_conflict" else 422, detail=details.get(str(exc), "批量上传无效"))


@router.get("/document-batches/{batch_id}", response_model=IngestionBatchRead)
def get_document_batch_endpoint(workspace_id: str, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, workspace_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch


@router.post("/document-batches/{batch_id}/retry", response_model=IngestionBatchRead, status_code=status.HTTP_202_ACCEPTED)
def retry_document_batch_endpoint(workspace_id: str, batch_id: str, db: Session = Depends(get_db)):
    batch = retry_batch(db, get_settings(), workspace_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch


@router.post("/document-batches/{batch_id}/cancel", response_model=IngestionBatchRead, status_code=status.HTTP_202_ACCEPTED)
def cancel_document_batch_endpoint(workspace_id: str, batch_id: str, db: Session = Depends(get_db)):
    batch = cancel_batch(db, workspace_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch


@router.post("/rag/query", response_model=RetrievalResponse)
def query_documents_endpoint(workspace_id: str, payload: RetrievalQuery, db: Session = Depends(get_db)):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    try:
        trace_id, results = retrieve(db, get_settings(), workspace_id, payload.query, payload.top_k)
    except Exception:
        logger.exception("document_query_failed workspace_id=%s", workspace_id)
        raise HTTPException(status_code=503, detail="检索服务暂不可用")
    return RetrievalResponse(trace_id=trace_id, query=payload.query, results=results)


@router.post("/rag/answer", response_model=AnswerResponse)
def answer_documents_endpoint(workspace_id: str, payload: AnswerRequest, db: Session = Depends(get_db)):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    try:
        return answer_question(db, get_settings(), workspace_id, payload.question, payload.top_k, payload.document_ids)
    except ValueError as exc:
        messages = {
            "generation_provider_unconfigured": "回答模型尚未配置",
            "invalid_model_output": "回答模型返回格式无效，请重试",
            "generation_provider_unavailable": "回答服务暂不可用",
        }
        code = str(exc)
        raise HTTPException(status_code=503 if code != "invalid_model_output" else 502, detail=messages.get(code, "回答服务暂不可用"))
    except RuntimeError:
        logger.exception("document_answer_retrieval_failed workspace_id=%s", workspace_id)
        raise HTTPException(status_code=503, detail="检索服务暂不可用")

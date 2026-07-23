from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.practice import (
    PracticeAttemptCreate,
    PracticeAttemptRead,
    PracticeJobRead,
    PracticeSetCreate,
    PracticeSetListItem,
    PracticeSetRead,
    ItemTypeMode,
    CodeLanguage,
)
from learn_platform_api.services.practice import (
    cancel_job,
    create_generation_job,
    delete_attempt,
    delete_set,
    get_attempt,
    get_job,
    get_set,
    list_attempts,
    list_sets,
    retry_job,
    submit_attempt,
    _science_verification_read,
)
from learn_platform_api.settings import get_settings


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["practice"])

CONFLICT_CODES = {
    "idempotency_key_conflict",
    "practice_generation_active",
    "course_version_inactive",
    "source_snapshot_stale",
}


def _practice_http_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    return HTTPException(status_code=409 if code in CONFLICT_CODES else 422, detail=code)


@router.get(
    "/courses/{course_id}/versions/{course_version_id}/lessons/{lesson_id}/versions/{lesson_version_id}/practice-sets",
    response_model=list[PracticeSetListItem],
)
def list_sets_endpoint(workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str, db: Session = Depends(get_db)):
    return list_sets(db, workspace_id, course_id, course_version_id, lesson_id, lesson_version_id)


@router.post(
    "/courses/{course_id}/versions/{course_version_id}/lessons/{lesson_id}/versions/{lesson_version_id}/practice-sets",
    response_model=PracticeJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_set_endpoint(
    workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str,
    payload: PracticeSetCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(422, "生成练习需要有效的 Idempotency-Key")
    if not payload.external_processing_ack:
        raise HTTPException(422, "生成练习前必须确认外部处理课程资料片段")
    try:
        return get_job_read(db, create_generation_job(db, get_settings(), workspace_id, course_id, course_version_id, lesson_id, lesson_version_id, payload, idempotency_key))
    except LookupError:
        raise HTTPException(404, "课程或课节不存在")
    except ValueError as exc:
        raise _practice_http_error(exc)


@router.get("/practice-sets/{set_id}", response_model=PracticeSetRead)
def get_set_endpoint(workspace_id: str, set_id: str, db: Session = Depends(get_db)):
    detail = get_set(db, workspace_id, set_id)
    if detail is None:
        raise HTTPException(404, "练习集合不存在")
    return detail


@router.delete("/practice-sets/{set_id}", status_code=202)
def delete_set_endpoint(workspace_id: str, set_id: str, db: Session = Depends(get_db)):
    if not delete_set(db, get_settings(), workspace_id, set_id):
        raise HTTPException(404, "练习集合不存在")


@router.get("/practice-jobs/{job_id}", response_model=PracticeJobRead)
def get_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = get_job(db, workspace_id, job_id)
    if job is None:
        raise HTTPException(404, "练习任务不存在")
    return get_job_read(db, job)


@router.post("/practice-jobs/{job_id}/cancel", response_model=PracticeJobRead)
def cancel_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = cancel_job(db, workspace_id, job_id)
    if job is None:
        raise HTTPException(404, "练习任务不存在")
    return get_job_read(db, job)


@router.post("/practice-jobs/{job_id}/retry", response_model=PracticeJobRead, status_code=202)
def retry_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        job = retry_job(db, get_settings(), workspace_id, job_id)
    except ValueError:
        raise HTTPException(409, "当前练习任务不能重试")
    if job is None:
        raise HTTPException(404, "练习任务不存在")
    return get_job_read(db, job)


@router.post("/practice-items/{item_id}/attempts", response_model=PracticeAttemptRead)
def submit_attempt_endpoint(workspace_id: str, item_id: str, payload: PracticeAttemptCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(422, "提交作答需要有效的 Idempotency-Key")
    try:
        attempt = submit_attempt(db, get_settings(), workspace_id, item_id, payload, idempotency_key)
    except LookupError:
        raise HTTPException(404, "题目不存在")
    except ValueError as exc:
        raise _practice_http_error(exc)
    detail = get_attempt(db, workspace_id, attempt.id)
    return detail


@router.get("/practice-items/{item_id}/attempts", response_model=list[PracticeAttemptRead])
def list_attempts_endpoint(workspace_id: str, item_id: str, db: Session = Depends(get_db)):
    return list_attempts(db, workspace_id, item_id)


@router.get("/practice-attempts/{attempt_id}", response_model=PracticeAttemptRead)
def get_attempt_endpoint(workspace_id: str, attempt_id: str, db: Session = Depends(get_db)):
    detail = get_attempt(db, workspace_id, attempt_id)
    if detail is None:
        raise HTTPException(404, "作答不存在")
    return detail


@router.delete("/practice-attempts/{attempt_id}", status_code=202)
def delete_attempt_endpoint(workspace_id: str, attempt_id: str, db: Session = Depends(get_db)):
    if not delete_attempt(db, get_settings(), workspace_id, attempt_id):
        raise HTTPException(404, "作答不存在")


def get_job_read(db: Session, job) -> PracticeJobRead:
    return PracticeJobRead(
        id=job.id, job_type=job.job_type, practice_set_id=job.practice_set_id, practice_attempt_id=job.practice_attempt_id,
        status=job.status, attempt_count=job.attempt_count, error_code=job.error_code, error_message=job.error_message,
        created_at=job.created_at, updated_at=job.updated_at,
        science_verification=_science_verification_read(db, job.id, "VerifyScientificAnswer", "reference_answer") if job.job_type == "generate_set" else None,
    )

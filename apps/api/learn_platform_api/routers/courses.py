from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Workspace
from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.courses import ActivateCourseVersion, CourseCreate, CourseCreateRead, CourseGenerationJobRead, CourseRead, LessonGenerationCreate, OutlineGenerationCreate, PublishLessonVersion
from learn_platform_api.services.courses import activate_course_version, cancel_job, course_detail, create_course, create_lesson_job, create_outline_job, delete_course, get_course, get_job, list_courses, list_generation_jobs, publish_lesson, reader, retry_generation_job
from learn_platform_api.settings import get_settings
from learn_platform_api.services.workspaces import workspace_is_active


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["courses"])


@router.get("/courses", response_model=list[CourseRead])
def list_courses_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return list_courses(db, workspace_id)


@router.post("/courses", response_model=CourseCreateRead, status_code=status.HTTP_202_ACCEPTED)
def create_course_endpoint(workspace_id: str, payload: CourseCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="创建课程需要有效的 Idempotency-Key")
    if not payload.external_processing_ack:
        raise HTTPException(status_code=422, detail="创建课程前必须确认外部处理资料片段")
    try:
        course, job, source_version_ids = create_course(db, get_settings(), workspace_id, payload.title, payload.goal, payload.audience, payload.document_ids, payload.output_language, idempotency_key)
    except LookupError:
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    except ValueError as exc:
        messages = {"source_not_ready": "只能选择当前 ready 资料", "duplicate_sources": "资料不能重复选择", "idempotency_key_conflict": "同一 Idempotency-Key 不能用于不同课程请求"}
        raise HTTPException(status_code=409 if str(exc) == "idempotency_key_conflict" else 422, detail=messages.get(str(exc), "课程来源无效"))
    return {"course": course, "job": job, "source_document_version_ids": source_version_ids}


@router.get("/courses/{course_id}")
def get_course_endpoint(workspace_id: str, course_id: str, db: Session = Depends(get_db)):
    course = get_course(db, workspace_id, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course_detail(db, course)


@router.get("/course-generation-jobs/{job_id}", response_model=CourseGenerationJobRead)
def get_course_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = get_job(db, workspace_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/course-generation-jobs", response_model=list[CourseGenerationJobRead])
def list_course_jobs_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    if not workspace_is_active(db, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return list_generation_jobs(db, workspace_id)


@router.post("/course-generation-jobs/{job_id}/cancel", response_model=CourseGenerationJobRead, status_code=202)
def cancel_course_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = cancel_job(db, workspace_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/course-generation-jobs/{job_id}/retry", response_model=CourseGenerationJobRead, status_code=202)
def retry_course_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        job = retry_generation_job(db, get_settings(), workspace_id, job_id)
    except ValueError:
        raise HTTPException(status_code=409, detail="当前任务不能重试")
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/courses/{course_id}/outline-generations", response_model=CourseGenerationJobRead, status_code=202)
def create_outline_generation_endpoint(workspace_id: str, course_id: str, payload: OutlineGenerationCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="生成大纲需要有效的 Idempotency-Key")
    if not payload.external_processing_ack:
        raise HTTPException(status_code=422, detail="生成大纲前必须确认外部处理资料片段")
    try:
        return create_outline_job(db, get_settings(), workspace_id, course_id, payload.document_ids, payload.output_language, idempotency_key)
    except LookupError:
        raise HTTPException(status_code=404, detail="课程不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409 if str(exc) == "idempotency_key_conflict" else 422, detail="同一 Idempotency-Key 不能用于不同生成请求" if str(exc) == "idempotency_key_conflict" else "课程来源无效")


@router.post("/courses/{course_id}/versions/{version_id}/lessons/{lesson_id}/generations", response_model=CourseGenerationJobRead, status_code=202)
def create_lesson_generation_endpoint(workspace_id: str, course_id: str, version_id: str, lesson_id: str, payload: LessonGenerationCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="生成课节需要有效的 Idempotency-Key")
    if not payload.external_processing_ack:
        raise HTTPException(status_code=422, detail="生成课节前必须确认外部处理资料片段")
    try:
        return create_lesson_job(db, get_settings(), workspace_id, course_id, version_id, lesson_id, payload.output_language, idempotency_key)
    except LookupError:
        raise HTTPException(status_code=404, detail="课程版本或课节不存在")
    except ValueError as exc:
        messages = {
            "idempotency_key_conflict": "同一 Idempotency-Key 不能用于不同生成请求",
            "lesson_generation_active": "这个课节已有生成任务正在进行",
        }
        raise HTTPException(status_code=409, detail=messages.get(str(exc), "课程来源已变化，不能继续生成"))


@router.post("/lessons/{lesson_id}/versions/{lesson_version_id}/publish")
def publish_lesson_endpoint(workspace_id: str, lesson_id: str, lesson_version_id: str, payload: PublishLessonVersion, db: Session = Depends(get_db)):
    try:
        return publish_lesson(db, workspace_id, lesson_id, lesson_version_id, payload.expected_current_published_version_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="课节版本不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="课程来源已变化" if str(exc) == "source_snapshot_stale" else "课节版本不能发布")


@router.post("/courses/{course_id}/versions/{version_id}/activate")
def activate_course_version_endpoint(workspace_id: str, course_id: str, version_id: str, payload: ActivateCourseVersion, db: Session = Depends(get_db)):
    try:
        return activate_course_version(db, workspace_id, course_id, version_id, payload.expected_current_active_version_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="课程版本不存在")
    except ValueError as exc:
        messages = {"no_published_lesson": "至少发布一个课节后才能激活", "activation_conflict": "课程当前版本已变化，请刷新后重试"}
        raise HTTPException(status_code=409, detail=messages.get(str(exc), "课程来源已变化"))


@router.get("/courses/{course_id}/reader")
def course_reader_endpoint(workspace_id: str, course_id: str, db: Session = Depends(get_db)):
    course = get_course(db, workspace_id, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    try:
        return reader(db, course)
    except ValueError:
        raise HTTPException(status_code=409, detail="课程尚未激活")


@router.delete("/courses/{course_id}", status_code=204)
def delete_course_endpoint(workspace_id: str, course_id: str, db: Session = Depends(get_db)):
    if not delete_course(db, workspace_id, course_id):
        raise HTTPException(status_code=404, detail="课程不存在")

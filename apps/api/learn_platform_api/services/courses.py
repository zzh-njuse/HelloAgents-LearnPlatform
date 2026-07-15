from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Course, CourseGenerationJob, CourseGenerationJobSource, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion, Lesson, LessonCitation, LessonVersion, SourceDocument, Workspace
from learn_platform_api.services.queue import enqueue_course_generation_job
from learn_platform_api.settings import Settings
from learn_platform_api.services.workspaces import workspace_is_active


def _sources(db: Session, workspace_id: str, document_ids: list[str]) -> list[tuple[SourceDocument, DocumentVersion]]:
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("duplicate_sources")
    rows = list(db.execute(select(SourceDocument, DocumentVersion).join(DocumentVersion, SourceDocument.current_version_id == DocumentVersion.id).where(SourceDocument.workspace_id == workspace_id, SourceDocument.id.in_(document_ids), SourceDocument.lifecycle_status == "active", DocumentVersion.processing_status == "ready")).all())
    if len(rows) != len(document_ids):
        raise ValueError("source_not_ready")
    by_id = {document.id: (document, version) for document, version in rows}
    return [by_id[document_id] for document_id in document_ids]


def _read(course: Course) -> dict[str, object]:
    return {"id": course.id, "workspace_id": course.workspace_id, "title": course.title, "goal": course.goal, "audience": course.audience, "lifecycle_status": course.lifecycle_status, "current_active_version_id": course.current_active_version_id, "created_at": course.created_at, "updated_at": course.updated_at, "source_degraded": False}


def create_course(db: Session, settings: Settings, workspace_id: str, title: str, goal: str, audience: str | None, document_ids: list[str], output_language: str, idempotency_key: str) -> tuple[dict[str, object], CourseGenerationJob, list[str]]:
    if not workspace_is_active(db, workspace_id):
        raise LookupError("workspace_not_found")
    existing = db.scalar(select(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id, CourseGenerationJob.idempotency_key == idempotency_key))
    if existing:
        course = db.get(Course, existing.course_id)
        existing_sources = list(db.scalars(select(CourseGenerationJobSource).where(CourseGenerationJobSource.course_generation_job_id == existing.id)))
        if not course or course.title != title or course.goal != goal or course.audience != audience or existing.output_language != output_language or {row.document_id for row in existing_sources} != set(document_ids):
            raise ValueError("idempotency_key_conflict")
        return _read(course), existing, [row.document_version_id for row in existing_sources]
    rows = _sources(db, workspace_id, document_ids)
    try:
        course = Course(workspace_id=workspace_id, title=title, goal=goal, audience=audience)
        db.add(course); db.flush()
        job = CourseGenerationJob(workspace_id=workspace_id, course_id=course.id, job_type="course_outline", output_language=output_language, status="queued", idempotency_key=idempotency_key)
        db.add(job); db.flush()
        db.add_all(CourseGenerationJobSource(course_generation_job_id=job.id, workspace_id=workspace_id, document_id=document.id, document_version_id=version.id) for document, version in rows)
        db.commit(); db.refresh(course); db.refresh(job)
    except IntegrityError:
        db.rollback()
        return create_course(db, settings, workspace_id, title, goal, audience, document_ids, output_language, idempotency_key)
    try:
        enqueue_course_generation_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_failed"; job.error_message = "课程生成队列暂不可用，可稍后重试"; db.commit(); db.refresh(job)
    return _read(course), job, [version.id for _, version in rows]


def list_courses(db: Session, workspace_id: str) -> list[dict[str, object]]:
    return [course_read(db, course) for course in db.scalars(select(Course).where(Course.workspace_id == workspace_id, Course.lifecycle_status == "active").order_by(Course.created_at.desc()))]


def source_degraded(db: Session, course_version_id: str | None) -> bool:
    if not course_version_id:
        return False
    sources = list(db.execute(select(CourseVersionSource, SourceDocument, DocumentVersion).join(SourceDocument, CourseVersionSource.document_id == SourceDocument.id).join(DocumentVersion, CourseVersionSource.document_version_id == DocumentVersion.id).where(CourseVersionSource.course_version_id == course_version_id)).all())
    return not sources or any(document.lifecycle_status != "active" or document.current_version_id != version.id or version.processing_status != "ready" for _, document, version in sources)


def course_read(db: Session, course: Course) -> dict[str, object]:
    value = _read(course)
    value["source_degraded"] = source_degraded(db, course.current_active_version_id)
    version_id = course.current_active_version_id or db.scalar(
        select(CourseVersion.id)
        .where(CourseVersion.course_id == course.id)
        .order_by(CourseVersion.version_number.desc())
        .limit(1)
    )
    value["source_count"] = 0
    value["published_lesson_count"] = 0
    value["pending_lesson_count"] = 0
    if version_id:
        value["source_count"] = db.scalar(
            select(func.count()).select_from(CourseVersionSource).where(CourseVersionSource.course_version_id == version_id)
        ) or 0
        total = db.scalar(select(func.count()).select_from(Lesson).where(Lesson.course_version_id == version_id)) or 0
        published = db.scalar(
            select(func.count()).select_from(Lesson).where(
                Lesson.course_version_id == version_id,
                Lesson.current_published_version_id.is_not(None),
            )
        ) or 0
        value["published_lesson_count"] = published
        value["pending_lesson_count"] = total - published
    value["latest_job"] = db.scalar(
        select(CourseGenerationJob)
        .where(CourseGenerationJob.course_id == course.id)
        .order_by(CourseGenerationJob.created_at.desc())
        .limit(1)
    )
    return value


def get_course(db: Session, workspace_id: str, course_id: str) -> Course | None:
    return db.scalar(select(Course).where(Course.id == course_id, Course.workspace_id == workspace_id, Course.lifecycle_status == "active"))


def get_job(db: Session, workspace_id: str, job_id: str) -> CourseGenerationJob | None:
    return db.scalar(select(CourseGenerationJob).where(CourseGenerationJob.id == job_id, CourseGenerationJob.workspace_id == workspace_id))


def list_generation_jobs(db: Session, workspace_id: str, limit: int = 20) -> list[CourseGenerationJob]:
    return list(db.scalars(
        select(CourseGenerationJob)
        .where(CourseGenerationJob.workspace_id == workspace_id)
        .order_by(CourseGenerationJob.created_at.desc())
        .limit(min(max(limit, 1), 50))
    ))


def create_lesson_job(db: Session, settings: Settings, workspace_id: str, course_id: str, version_id: str, lesson_id: str, output_language: str, idempotency_key: str) -> CourseGenerationJob:
    course = get_course(db, workspace_id, course_id)
    version = db.scalar(select(CourseVersion).where(CourseVersion.id == version_id, CourseVersion.course_id == course_id, CourseVersion.workspace_id == workspace_id))
    lesson = db.scalar(select(Lesson).where(Lesson.id == lesson_id, Lesson.course_version_id == version_id, Lesson.workspace_id == workspace_id))
    if not course or not version or not lesson:
        raise LookupError("lesson_not_found")
    if source_degraded(db, version.id):
        raise ValueError("source_snapshot_stale")
    existing = db.scalar(select(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id, CourseGenerationJob.idempotency_key == idempotency_key))
    if existing:
        if existing.course_id != course_id or existing.course_version_id != version_id or existing.lesson_id != lesson_id or existing.job_type != "lesson_draft" or existing.output_language != output_language:
            raise ValueError("idempotency_key_conflict")
        return existing
    active = db.scalar(select(CourseGenerationJob.id).where(
        CourseGenerationJob.workspace_id == workspace_id,
        CourseGenerationJob.lesson_id == lesson_id,
        CourseGenerationJob.job_type == "lesson_draft",
        CourseGenerationJob.status.in_({"queued", "running", "retry_wait", "cancel_requested"}),
    ).limit(1))
    if active:
        raise ValueError("lesson_generation_active")
    try:
        job = CourseGenerationJob(workspace_id=workspace_id, course_id=course_id, course_version_id=version_id, lesson_id=lesson_id, job_type="lesson_draft", output_language=output_language, status="queued", idempotency_key=idempotency_key)
        db.add(job); db.flush()
        for source in db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == version_id)):
            db.add(CourseGenerationJobSource(course_generation_job_id=job.id, workspace_id=workspace_id, document_id=source.document_id, document_version_id=source.document_version_id))
        db.commit(); db.refresh(job)
    except IntegrityError:
        db.rollback()
        return create_lesson_job(db, settings, workspace_id, course_id, version_id, lesson_id, output_language, idempotency_key)
    try:
        enqueue_course_generation_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_failed"; job.error_message = "课程生成队列暂不可用，可稍后重试"; db.commit(); db.refresh(job)
    return job


def create_outline_job(db: Session, settings: Settings, workspace_id: str, course_id: str, document_ids: list[str], output_language: str, idempotency_key: str) -> CourseGenerationJob:
    course = get_course(db, workspace_id, course_id)
    if not course:
        raise LookupError("course_not_found")
    rows = _sources(db, workspace_id, document_ids)
    existing = db.scalar(select(CourseGenerationJob).where(CourseGenerationJob.workspace_id == workspace_id, CourseGenerationJob.idempotency_key == idempotency_key))
    if existing:
        existing_sources = set(db.scalars(select(CourseGenerationJobSource.document_id).where(CourseGenerationJobSource.course_generation_job_id == existing.id)))
        if existing.course_id != course_id or existing.job_type != "course_outline" or existing.output_language != output_language or existing_sources != set(document_ids):
            raise ValueError("idempotency_key_conflict")
        return existing
    try:
        job = CourseGenerationJob(workspace_id=workspace_id, course_id=course_id, job_type="course_outline", output_language=output_language, status="queued", idempotency_key=idempotency_key)
        db.add(job); db.flush()
        db.add_all(CourseGenerationJobSource(course_generation_job_id=job.id, workspace_id=workspace_id, document_id=document.id, document_version_id=version.id) for document, version in rows)
        db.commit(); db.refresh(job)
    except IntegrityError:
        db.rollback()
        return create_outline_job(db, settings, workspace_id, course_id, document_ids, output_language, idempotency_key)
    try:
        enqueue_course_generation_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_failed"; job.error_message = "课程生成队列暂不可用，可稍后重试"; db.commit(); db.refresh(job)
    return job


def retry_generation_job(db: Session, settings: Settings, workspace_id: str, job_id: str) -> CourseGenerationJob | None:
    job = get_job(db, workspace_id, job_id)
    if not job:
        return None
    if job.status not in {"failed", "queue_failed"}:
        raise ValueError("job_not_retryable")
    job.status = "queued"; job.error_code = None; job.error_message = None; job.next_attempt_at = None
    db.commit()
    try:
        enqueue_course_generation_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_failed"; job.error_message = "课程生成队列暂不可用，可稍后重试"; db.commit()
    db.refresh(job)
    return job


def publish_lesson(db: Session, workspace_id: str, lesson_id: str, lesson_version_id: str, expected_current_version_id: str | None) -> LessonVersion:
    lesson = db.scalar(select(Lesson).where(Lesson.id == lesson_id, Lesson.workspace_id == workspace_id).with_for_update())
    version = db.scalar(select(LessonVersion).where(LessonVersion.id == lesson_version_id, LessonVersion.lesson_id == lesson_id, LessonVersion.workspace_id == workspace_id))
    if not lesson or not version:
        raise LookupError("lesson_version_not_found")
    if lesson.current_published_version_id != expected_current_version_id:
        raise ValueError("publish_conflict")
    if version.status != "draft":
        raise ValueError("publish_conflict")
    if source_degraded(db, lesson.course_version_id):
        raise ValueError("source_snapshot_stale")
    if lesson.current_published_version_id:
        db.execute(update(LessonVersion).where(LessonVersion.id == lesson.current_published_version_id, LessonVersion.status == "published").values(status="superseded"))
    version.status = "published"; version.published_at = datetime.now(timezone.utc); lesson.current_published_version_id = version.id
    db.commit(); db.refresh(version)
    return version


def activate_course_version(db: Session, workspace_id: str, course_id: str, version_id: str, expected_current_version_id: str | None) -> CourseVersion:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.workspace_id == workspace_id, Course.lifecycle_status == "active").with_for_update())
    version = db.scalar(select(CourseVersion).where(CourseVersion.id == version_id, CourseVersion.course_id == course_id, CourseVersion.workspace_id == workspace_id))
    if not course or not version:
        raise LookupError("course_version_not_found")
    if course.current_active_version_id != expected_current_version_id:
        raise ValueError("activation_conflict")
    if source_degraded(db, version.id):
        raise ValueError("source_snapshot_stale")
    published = db.scalar(select(func.count()).select_from(Lesson).where(Lesson.course_version_id == version.id, Lesson.current_published_version_id.is_not(None))) or 0
    if published < 1:
        raise ValueError("no_published_lesson")
    if course.current_active_version_id and course.current_active_version_id != version.id:
        db.execute(update(CourseVersion).where(CourseVersion.id == course.current_active_version_id).values(status="archived"))
    version.status = "active"; course.current_active_version_id = version.id
    db.commit(); db.refresh(version)
    return version


def course_detail(db: Session, course: Course) -> dict[str, object]:
    versions = list(db.scalars(select(CourseVersion).where(CourseVersion.course_id == course.id).order_by(CourseVersion.version_number.desc())))
    outline = []
    for version in versions:
        sections = []
        for section in db.scalars(select(CourseSection).where(CourseSection.course_version_id == version.id).order_by(CourseSection.ordinal)):
            lessons = []
            for lesson in db.scalars(select(Lesson).where(Lesson.course_section_id == section.id).order_by(Lesson.ordinal)):
                drafts = list(db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.version_number.desc())))
                version_reads = []
                for draft in drafts:
                    citation_rows = list(db.execute(select(LessonCitation, DocumentChunk, SourceDocument).join(DocumentChunk, LessonCitation.document_chunk_id == DocumentChunk.id).join(SourceDocument, LessonCitation.document_id == SourceDocument.id).where(LessonCitation.lesson_version_id == draft.id)).all())
                    citations = [{"citation_id": citation.id, "block_key": citation.block_key, "document_id": citation.document_id, "document_version_id": citation.document_version_id, "chunk_id": citation.document_chunk_id, "document_name": document.display_name, "heading_path": chunk.heading_path.split(" / ") if chunk.heading_path else [], "start_offset": chunk.start_offset, "end_offset": chunk.end_offset, "page_start": chunk.page_start, "page_end": chunk.page_end, "available": document.lifecycle_status == "active" and document.current_version_id == citation.document_version_id} for citation, chunk, document in citation_rows]
                    by_block: dict[str, list[str]] = {}
                    for citation in citations:
                        by_block.setdefault(citation["block_key"], []).append(citation["citation_id"])
                    blocks = [{**block, "citation_ids": by_block.get(block["block_key"], [])} for block in (draft.blocks or [])]
                    version_reads.append({"id": draft.id, "version_number": draft.version_number, "status": draft.status, "title": draft.title, "learning_objectives": draft.learning_objectives or [], "blocks": blocks, "citations": citations})
                lessons.append({"id": lesson.id, "title": lesson.title, "objective": lesson.objective, "ordinal": lesson.ordinal, "current_published_version_id": lesson.current_published_version_id, "versions": version_reads})
            sections.append({"id": section.id, "title": section.title, "objective": section.objective, "ordinal": section.ordinal, "lessons": lessons})
        outline.append({"id": version.id, "version_number": version.version_number, "status": version.status, "title": version.title, "summary": version.summary, "source_degraded": source_degraded(db, version.id), "sections": sections})
    return {"course": course_read(db, course), "versions": outline}


def reader(db: Session, course: Course) -> dict[str, object]:
    if not course.current_active_version_id:
        raise ValueError("course_not_active")
    detail = course_detail(db, course)
    active = next((item for item in detail["versions"] if item["id"] == course.current_active_version_id), None)
    if not active:
        raise ValueError("active_version_missing")
    for section in active["sections"]:
        for lesson in section["lessons"]:
            lesson["published_version"] = next((item for item in lesson["versions"] if item["id"] == lesson["current_published_version_id"]), None)
            lesson.pop("versions", None)
    return {"course": detail["course"], "version": active}


def cancel_job(db: Session, workspace_id: str, job_id: str) -> CourseGenerationJob | None:
    job = get_job(db, workspace_id, job_id)
    if not job:
        return None
    if job.status in {"queued", "retry_wait"}:
        job.status = "canceled"
    elif job.status == "running":
        job.status = "cancel_requested"
    db.commit(); db.refresh(job)
    return job


def delete_course(db: Session, workspace_id: str, course_id: str) -> bool:
    course = get_course(db, workspace_id, course_id)
    if not course:
        return False
    course.lifecycle_status = "deleted"; course.deleted_at = datetime.now(timezone.utc); course.current_active_version_id = None
    db.execute(update(CourseGenerationJob).where(CourseGenerationJob.course_id == course.id, CourseGenerationJob.status.in_({"queued", "retry_wait"})).values(status="canceled"))
    db.execute(update(CourseGenerationJob).where(CourseGenerationJob.course_id == course.id, CourseGenerationJob.status == "running").values(status="cancel_requested"))
    db.commit()
    return True

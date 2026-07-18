from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Course, CourseVersion, Lesson, LessonCompletion, LessonVersion, Workspace


def list_completions(db: Session, workspace_id: str, course_id: str | None = None) -> list[dict]:
    statement = select(LessonCompletion).where(LessonCompletion.workspace_id == workspace_id)
    if course_id:
        statement = statement.where(LessonCompletion.course_id == course_id)
    rows = db.scalars(statement.order_by(LessonCompletion.completed_at.desc())).all()
    result = []
    for row in rows:
        lesson = db.get(Lesson, row.lesson_id)
        result.append({"id": row.id, "course_id": row.course_id, "course_version_id": row.course_version_id,
                       "lesson_id": row.lesson_id, "lesson_version_id": row.lesson_version_id,
                       "lesson_title": lesson.title if lesson else "已删除课节",
                       "is_current_version": bool(lesson and lesson.current_published_version_id == row.lesson_version_id),
                       "completed_at": row.completed_at.isoformat()})
    return result


def complete_lesson(db: Session, workspace_id: str, lesson_version_id: str) -> dict:
    workspace = db.get(Workspace, workspace_id)
    version = db.get(LessonVersion, lesson_version_id)
    lesson = db.get(Lesson, version.lesson_id) if version else None
    if not workspace or workspace.lifecycle_status != "active" or not version or not lesson:
        raise LookupError("lesson_version_not_found")
    course_version = db.get(CourseVersion, version.course_version_id)
    course = db.get(Course, course_version.course_id) if course_version else None
    if (version.workspace_id != workspace_id or lesson.workspace_id != workspace_id or version.status != "published"
            or lesson.current_published_version_id != version.id or not course or course.workspace_id != workspace_id
            or course.lifecycle_status != "active" or course.current_active_version_id != version.course_version_id):
        raise LookupError("lesson_version_not_found")
    existing = db.scalar(select(LessonCompletion).where(
        LessonCompletion.workspace_id == workspace_id, LessonCompletion.lesson_version_id == version.id,
    ))
    if existing is None:
        existing = LessonCompletion(workspace_id=workspace_id, course_id=course.id,
            course_version_id=version.course_version_id, lesson_id=lesson.id, lesson_version_id=version.id,
            completed_at=datetime.now(timezone.utc))
        db.add(existing)
        try:
            db.commit()
            db.refresh(existing)
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(LessonCompletion).where(
                LessonCompletion.workspace_id == workspace_id,
                LessonCompletion.lesson_version_id == version.id,
            ))
            if existing is None:
                raise
    return {"id": existing.id, "course_id": existing.course_id, "course_version_id": existing.course_version_id,
            "lesson_id": existing.lesson_id, "lesson_version_id": existing.lesson_version_id,
            "lesson_title": lesson.title, "is_current_version": True,
            "completed_at": existing.completed_at.isoformat()}


def undo_completion(db: Session, workspace_id: str, lesson_version_id: str) -> bool:
    row = db.scalar(select(LessonCompletion).where(
        LessonCompletion.workspace_id == workspace_id, LessonCompletion.lesson_version_id == lesson_version_id,
    ))
    if row is None:
        return False
    db.delete(row); db.commit()
    return True

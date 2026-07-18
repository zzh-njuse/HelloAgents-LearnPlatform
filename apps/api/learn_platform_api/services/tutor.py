from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import AgentRun, AgentToolCall, Course, CourseSection, CourseVersion, Lesson, LessonVersion, SourceDocument, DocumentChunk, TutorSession, TutorTurn, TutorTurnCitation, Workspace
from learn_platform_api.services.queue import enqueue_tutor_session_deletion, enqueue_tutor_turn
from learn_platform_api.settings import Settings


ACTIVE_TURN_STATUSES = {"queued", "running", "retry_wait", "cancel_requested"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _session(db: Session, workspace_id: str, session_id: str, *, lock: bool = False) -> TutorSession | None:
    statement = select(TutorSession).where(TutorSession.id == session_id, TutorSession.workspace_id == workspace_id, TutorSession.status == "active")
    return db.scalar(statement.with_for_update() if lock else statement)


def list_sessions(db: Session, workspace_id: str, course_id: str, course_version_id: str) -> list[TutorSession]:
    return list(db.scalars(select(TutorSession).where(TutorSession.workspace_id == workspace_id, TutorSession.course_id == course_id, TutorSession.course_version_id == course_version_id, TutorSession.status == "active").order_by(TutorSession.updated_at.desc())))


def create_session(db: Session, settings: Settings, workspace_id: str, course_id: str, course_version_id: str) -> TutorSession:
    workspace = db.get(Workspace, workspace_id)
    if not workspace or workspace.lifecycle_status != "active":
        raise LookupError("workspace_not_found")
    course = db.get(Course, course_id)
    version = db.get(CourseVersion, course_version_id)
    if not course or not version or course.workspace_id != workspace_id or course.lifecycle_status != "active" or version.course_id != course.id:
        raise LookupError("course_version_not_found")
    if course.current_active_version_id != version.id:
        raise ValueError("course_version_inactive")
    session = TutorSession(workspace_id=workspace_id, course_id=course.id, course_version_id=version.id, provider=settings.product_generation_provider, model=settings.product_generation_model, external_processing_ack_at=now())
    db.add(session); db.commit(); db.refresh(session)
    return session


def create_turn(db: Session, settings: Settings, workspace_id: str, session_id: str, payload, idempotency_key: str) -> TutorTurn:
    session = _session(db, workspace_id, session_id, lock=True)
    if not session:
        raise LookupError("session_not_found")
    workspace = db.get(Workspace, workspace_id)
    if not workspace or workspace.lifecycle_status != "active":
        raise LookupError("session_not_found")
    course = db.get(Course, session.course_id)
    if not course or course.lifecycle_status != "active" or course.current_active_version_id != session.course_version_id:
        raise ValueError("course_version_inactive")
    existing = db.scalar(select(TutorTurn).where(TutorTurn.session_id == session.id, TutorTurn.idempotency_key == idempotency_key))
    if existing:
        if (existing.question, existing.scope, existing.section_id, existing.lesson_id, existing.lesson_version_id) != (payload.question.strip(), payload.scope, payload.section_id, payload.lesson_id, payload.lesson_version_id):
            raise ValueError("idempotency_key_conflict")
        return existing
    active = db.scalar(select(TutorTurn.id).where(TutorTurn.session_id == session.id, TutorTurn.status.in_(ACTIVE_TURN_STATUSES)))
    if active:
        raise ValueError("active_turn_exists")
    if payload.scope == "lesson":
        section = db.get(CourseSection, payload.section_id)
        lesson = db.get(Lesson, payload.lesson_id)
        version = db.get(LessonVersion, payload.lesson_version_id)
        if not section or not lesson or not version or section.course_version_id != session.course_version_id or lesson.course_section_id != section.id or lesson.course_version_id != session.course_version_id or version.lesson_id != lesson.id or version.course_version_id != session.course_version_id or version.status != "published" or lesson.current_published_version_id != version.id:
            raise ValueError("lesson_version_mismatch")
    session.last_turn_ordinal += 1
    turn = TutorTurn(session_id=session.id, workspace_id=workspace_id, ordinal=session.last_turn_ordinal, attempt_number=1, idempotency_key=idempotency_key, status="queued", question=payload.question.strip(), scope=payload.scope, section_id=payload.section_id, lesson_id=payload.lesson_id, lesson_version_id=payload.lesson_version_id, history_through_ordinal=session.last_turn_ordinal - 1)
    db.add(turn); db.commit(); db.refresh(turn)
    try:
        enqueue_tutor_turn(settings, turn.id)
    except Exception:
        turn.status = "queue_failed"; turn.error_code = "queue_unavailable"; turn.error_message = "Tutor 队列暂时不可用"; db.commit()
    return turn


def get_turn(db: Session, workspace_id: str, turn_id: str) -> TutorTurn | None:
    return db.scalar(select(TutorTurn).where(TutorTurn.id == turn_id, TutorTurn.workspace_id == workspace_id))


def session_detail(db: Session, session: TutorSession) -> dict:
    return {"id": session.id, "workspace_id": session.workspace_id, "course_id": session.course_id, "course_version_id": session.course_version_id, "status": session.status, "provider": session.provider, "model": session.model, "created_at": session.created_at.isoformat(), "turns": [turn_detail(db, turn) for turn in db.scalars(select(TutorTurn).where(TutorTurn.session_id == session.id).order_by(TutorTurn.ordinal, TutorTurn.attempt_number))]}


def turn_detail(db: Session, turn: TutorTurn) -> dict:
    citations = []
    for citation, chunk, document in db.execute(select(TutorTurnCitation, DocumentChunk, SourceDocument).join(DocumentChunk, TutorTurnCitation.document_chunk_id == DocumentChunk.id).join(SourceDocument, TutorTurnCitation.document_id == SourceDocument.id).where(TutorTurnCitation.turn_id == turn.id)):
        citations.append({"citation_id": citation.citation_id, "block_key": citation.block_key, "document_id": citation.document_id, "document_version_id": citation.document_version_id, "chunk_id": chunk.id, "document_name": document.display_name, "heading_path": (chunk.heading_path or "").split(" / ") if chunk.heading_path else [], "start_offset": chunk.start_offset, "end_offset": chunk.end_offset, "page_start": chunk.page_start, "page_end": chunk.page_end})
    memory_count = db.scalar(
        select(AgentToolCall.result_count).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id)
        .where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext")
        .order_by(AgentToolCall.created_at.desc()).limit(1)
    ) or 0
    completion_count = db.scalar(
        select(AgentToolCall.result_count).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id)
        .where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LessonCompletionContext")
        .order_by(AgentToolCall.created_at.desc()).limit(1)
    ) or 0
    return {"id": turn.id, "session_id": turn.session_id, "ordinal": turn.ordinal, "attempt_number": turn.attempt_number, "status": turn.status, "question": turn.question, "scope": turn.scope, "section_id": turn.section_id, "lesson_id": turn.lesson_id, "lesson_version_id": turn.lesson_version_id, "answer_blocks": turn.answer_blocks, "citations": citations, "error_code": turn.error_code, "error_message": turn.error_message, "created_at": turn.created_at.isoformat(), "completed_at": turn.completed_at.isoformat() if turn.completed_at else None, "memory_count": memory_count, "completion_count": completion_count}


def cancel_turn(db: Session, workspace_id: str, turn_id: str) -> TutorTurn | None:
    turn = db.scalar(
        select(TutorTurn)
        .where(TutorTurn.id == turn_id, TutorTurn.workspace_id == workspace_id)
        .with_for_update()
    )
    if turn and turn.status in ACTIVE_TURN_STATUSES:
        turn.status = "canceled" if turn.status in {"queued", "queue_failed", "retry_wait"} else "cancel_requested"
        if turn.status == "canceled": turn.completed_at = now()
        db.commit()
    return turn


def retry_turn(db: Session, settings: Settings, workspace_id: str, turn_id: str) -> TutorTurn | None:
    original = get_turn(db, workspace_id, turn_id)
    if not original: return None
    if original.status not in {"failed", "canceled", "queue_failed"}: raise ValueError("turn_not_retryable")
    session = _session(db, workspace_id, original.session_id, lock=True)
    if not session: raise ValueError("session_not_active")
    active = db.scalar(select(TutorTurn.id).where(TutorTurn.session_id == session.id, TutorTurn.status.in_(ACTIVE_TURN_STATUSES)))
    if active:
        raise ValueError("active_turn_exists")
    retry = TutorTurn(session_id=session.id, workspace_id=workspace_id, ordinal=original.ordinal, attempt_number=original.attempt_number + 1, idempotency_key=str(uuid4()), status="queued", question=original.question, scope=original.scope, section_id=original.section_id, lesson_id=original.lesson_id, lesson_version_id=original.lesson_version_id, history_through_ordinal=original.history_through_ordinal)
    db.add(retry); db.commit(); db.refresh(retry)
    try: enqueue_tutor_turn(settings, retry.id)
    except Exception:
        retry.status = "queue_failed"; retry.error_code = "queue_unavailable"; retry.error_message = "Tutor 队列暂时不可用"; db.commit()
    return retry


def delete_session(db: Session, settings: Settings, workspace_id: str, session_id: str) -> bool:
    session = db.scalar(select(TutorSession).where(TutorSession.id == session_id, TutorSession.workspace_id == workspace_id, TutorSession.status.in_({"active", "deleting"})).with_for_update())
    if not session: return False
    for turn in db.scalars(select(TutorTurn).where(TutorTurn.session_id == session.id, TutorTurn.status.in_(ACTIVE_TURN_STATUSES))):
        turn.status = "cancel_requested"
    session.status = "deleting"; session.deleted_at = now(); db.commit()
    try: enqueue_tutor_session_deletion(settings, session.id)
    except Exception: pass
    return True


def cleanup_session(db: Session, session_id: str) -> bool:
    session = db.scalar(select(TutorSession).where(TutorSession.id == session_id, TutorSession.status == "deleting").with_for_update())
    if not session: return False
    turn_ids = select(TutorTurn.id).where(TutorTurn.session_id == session.id)
    run_ids = select(AgentRun.id).where(AgentRun.tutor_turn_id.in_(turn_ids))
    db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
    db.execute(delete(AgentRun).where(AgentRun.tutor_turn_id.in_(turn_ids)))
    db.delete(session); db.commit()
    return True

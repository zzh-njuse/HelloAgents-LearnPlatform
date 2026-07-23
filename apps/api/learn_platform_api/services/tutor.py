from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from academic_companion.teaching_skills import SkillUnavailable, current_published, display_name_for, load_skill
from learn_platform_api.db.models import AgentRun, AgentToolCall, CodeLabRun, Course, CourseSection, CourseVersion, Lesson, LessonVersion, SourceDocument, DocumentChunk, TutorSession, TutorTurn, TutorTurnCitation, TutorTurnCodeRun, TutorTurnToolAuthorization, Workspace
from learn_platform_api.services.queue import enqueue_tutor_session_deletion, enqueue_tutor_turn
from learn_platform_api.settings import Settings


ACTIVE_TURN_STATUSES = {"queued", "running", "retry_wait", "cancel_requested"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_teaching_skill_snapshot() -> dict[str, str]:
    """Resolve the single current published skill into an immutable snapshot.

    Returns ``{id, version, hash, display_name}``. Raises
    ``ValueError("teaching_skill_unavailable")`` if the allowlist points at a
    skill that cannot be loaded or hash-verified — new turns never carry a
    partial snapshot and never silently fall back (Spec 003 §5.7, §12).
    """
    skill_id, version = current_published()
    try:
        skill = load_skill(skill_id, version)
    except SkillUnavailable as exc:
        raise ValueError("teaching_skill_unavailable") from exc
    return {"id": skill.skill_id, "version": skill.version, "hash": skill.content_hash, "display_name": skill.display_name}


def teaching_skill_capability() -> dict[str, str]:
    """Public, hash-free projection of the current published skill."""
    snapshot = resolve_teaching_skill_snapshot()
    return {"id": snapshot["id"], "display_name": snapshot["display_name"], "version": snapshot["version"]}


def _teaching_skill_projection(turn: TutorTurn) -> dict[str, str] | None:
    """Project a turn's snapshot for the API, or ``None`` for historical turns."""
    if not turn.teaching_skill_id or not turn.teaching_skill_version:
        return None
    display_name = display_name_for(turn.teaching_skill_id, turn.teaching_skill_version) or turn.teaching_skill_id
    return {"id": turn.teaching_skill_id, "display_name": display_name, "version": turn.teaching_skill_version}


def _session(db: Session, workspace_id: str, session_id: str, *, lock: bool = False) -> TutorSession | None:
    workspace_statement = select(Workspace.id).where(
        Workspace.id == workspace_id,
        Workspace.lifecycle_status == "active",
    )
    if db.scalar(workspace_statement.with_for_update() if lock else workspace_statement) is None:
        return None
    statement = select(TutorSession).where(TutorSession.id == session_id, TutorSession.workspace_id == workspace_id, TutorSession.status == "active")
    return db.scalar(statement.with_for_update() if lock else statement)


def list_sessions(db: Session, workspace_id: str, course_id: str, course_version_id: str) -> list[TutorSession]:
    if db.scalar(select(Workspace.id).where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")) is None:
        raise LookupError("workspace_not_found")
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
    # Resolve the deterministic current teaching skill once; every new Slice 3
    # turn carries the full id/version/hash snapshot. The client cannot supply
    # these and the resolved snapshot is part of idempotency authority, so a
    # duplicate delivery cannot create a second turn/run under a different skill
    # snapshot (Spec 003 §10, ADR 005 §3.2/§3.4). A missing/tampered skill fails
    # creation explicitly instead of silently falling back.
    snapshot = resolve_teaching_skill_snapshot()
    existing = db.scalar(select(TutorTurn).where(TutorTurn.session_id == session.id, TutorTurn.idempotency_key == idempotency_key))
    if existing:
        # Full server-resolved skill authority: id + version + hash must all match
        # (corr 3.8), so a replay under a different resolved snapshot conflicts
        # rather than returning a half-matching turn.
        # Slice 4: science_tool_authorized is part of idempotency authority.
        existing_auth = db.scalar(
            select(TutorTurnToolAuthorization).where(
                TutorTurnToolAuthorization.turn_id == existing.id,
                TutorTurnToolAuthorization.capability_id == "science_computation",
            )
        )
        existing_science = existing_auth is not None
        # Slice 4: code tool authorization is part of idempotency authority.
        existing_code_auth = db.scalar(
            select(TutorTurnToolAuthorization).where(
                TutorTurnToolAuthorization.turn_id == existing.id,
                TutorTurnToolAuthorization.capability_id == "code_execution",
            )
        )
        existing_code = existing_code_auth is not None
        # Slice 4: code_run_id is part of idempotency authority (correction 003 §3).
        # Same idempotency key with a different code_run_id must 409, not return old Turn.
        existing_code_run_assoc = db.scalar(
            select(TutorTurnCodeRun).where(
                TutorTurnCodeRun.turn_id == existing.id,
            )
        )
        existing_code_run_id = existing_code_run_assoc.code_lab_run_id if existing_code_run_assoc else None
        if (existing.question, existing.scope, existing.section_id, existing.lesson_id, existing.lesson_version_id,
                existing.teaching_skill_id, existing.teaching_skill_version, existing.teaching_skill_hash) != (
                payload.question.strip(), payload.scope, payload.section_id, payload.lesson_id, payload.lesson_version_id,
                snapshot["id"], snapshot["version"], snapshot["hash"]):
            raise ValueError("idempotency_key_conflict")
        if existing_science != getattr(payload, 'science_tool_authorized', False):
            raise ValueError("idempotency_key_conflict")
        if existing_code != getattr(payload, 'code_tool_authorized', False):
            raise ValueError("idempotency_key_conflict")
        if existing_code_run_id != getattr(payload, 'code_run_id', None):
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
    turn = TutorTurn(session_id=session.id, workspace_id=workspace_id, ordinal=session.last_turn_ordinal, attempt_number=1, idempotency_key=idempotency_key, status="queued", question=payload.question.strip(), scope=payload.scope, section_id=payload.section_id, lesson_id=payload.lesson_id, lesson_version_id=payload.lesson_version_id, history_through_ordinal=session.last_turn_ordinal - 1, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"])
    db.add(turn); db.flush()

    # Slice 4: Create science tool authorization snapshot if requested (Spec 004 §6.1, ADR 006 §2.7).
    # If capability is unavailable, request true returns stable science_tool_unavailable,
    # not silently changed to false.
    science_auth = getattr(payload, 'science_tool_authorized', False)
    if science_auth:
        if not settings.wolfram_mcp_enabled:
            raise ValueError("science_tool_unavailable")
        # Per correction 004 §5: the authorization snapshot must copy the
        # admin-verified canonical snapshot from the capability status projection,
        # NOT compute it from a dynamic handshake. The Turn authorization records
        # what the admin has already verified — if the projection doesn't exist
        # or hasn't been verified, the capability is not ready and authorization
        # must be refused.
        from learn_platform_api.services.readiness import _read_capability_projection
        projection = _read_capability_projection(db, "science_computation")
        if projection is None or not projection.get("ok"):
            raise ValueError("science_tool_unavailable")
        verified_hash = projection.get("verified_schema_hash", "")
        if not verified_hash:
            # No verified schema hash means the capability has never been
            # successfully probed — cannot authorize
            raise ValueError("science_tool_unavailable")
        import json
        auth = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id=turn.id,
            workspace_id=workspace_id,
            capability_id="science_computation",
            max_calls=settings.wolfram_max_calls_per_turn,
            used_calls=0,
            mcp_server_name="wolfram-cloud-mcp",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist=json.dumps(["WolframAlpha", "WolframContext"]),
            # Per correction 004 §5: copy the admin-verified canonical snapshot
            # from the capability projection. This is the complete准入 snapshot
            # that the admin has already verified — NOT a dynamic handshake hash.
            mcp_schema_hash=verified_hash,
        )
        db.add(auth)

    # Slice 4 packet 002: Create code tool authorization if requested (Spec 004 §8.1).
    # Independent from science authorization; both can be active on the same Turn.
    code_auth = getattr(payload, 'code_tool_authorized', False)
    if code_auth:
        if not settings.mcp_execution_adapter_url:
            raise ValueError("code_tool_unavailable")
        # Per Spec 004 §8.1: code execution capability must be ready
        from learn_platform_api.services.readiness import _read_capability_projection
        code_projection = _read_capability_projection(db, "code_execution")
        if code_projection is None or not code_projection.get("ok"):
            raise ValueError("code_tool_unavailable")
        code_verified_hash = code_projection.get("verified_schema_hash", "")
        if not code_verified_hash:
            raise ValueError("code_tool_unavailable")
        import json as _json
        code_auth_record = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id=turn.id,
            workspace_id=workspace_id,
            capability_id="code_execution",
            max_calls=settings.tutor_max_code_calls_per_turn,
            used_calls=0,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist=_json.dumps(["run_code"]),
            mcp_schema_hash=code_verified_hash,
        )
        db.add(code_auth_record)
        turn.code_tool_authorized = True

    # Slice 4: Code run safe summary association (Spec 004 §5.1, §9).
    # At most one code run per Turn; must be terminal, same workspace, not deleted.
    code_run_id = getattr(payload, 'code_run_id', None)
    if code_run_id:
        code_run = db.scalar(
            select(CodeLabRun).where(
                CodeLabRun.id == code_run_id,
                CodeLabRun.workspace_id == workspace_id,
                CodeLabRun.deleted_at.is_(None),
            )
        )
        if code_run is None:
            raise ValueError("code_run_not_found")
        if code_run.status not in ("succeeded", "failed", "completed", "compile_error", "runtime_error", "timed_out", "output_limited", "canceled"):
            raise ValueError("code_run_not_terminal")
        # Create the association — safe summary only, no private I/O
        db.add(TutorTurnCodeRun(
            turn_id=turn.id,
            code_lab_run_id=code_run_id,
            workspace_id=workspace_id,
        ))

    db.commit(); db.refresh(turn)
    try:
        enqueue_tutor_turn(settings, turn.id)
    except Exception:
        turn.status = "queue_failed"; turn.error_code = "queue_unavailable"; turn.error_message = "Tutor 队列暂时不可用"; db.commit()
    return turn


def get_turn(db: Session, workspace_id: str, turn_id: str) -> TutorTurn | None:
    if db.scalar(select(Workspace.id).where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")) is None:
        return None
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
    # Slice 4: science tool usage summary (Spec 004 §6.1, ADR 006 §2.7)
    science_auth = db.scalar(
        select(TutorTurnToolAuthorization).where(
            TutorTurnToolAuthorization.turn_id == turn.id,
            TutorTurnToolAuthorization.capability_id == "science_computation",
        )
    )
    science_tool_used = science_auth is not None and science_auth.used_calls > 0
    science_tool_call_count = science_auth.used_calls if science_auth else 0
    # Slice 4 packet 002: code tool usage summary (Spec 004 §8.1)
    code_auth = db.scalar(
        select(TutorTurnToolAuthorization).where(
            TutorTurnToolAuthorization.turn_id == turn.id,
            TutorTurnToolAuthorization.capability_id == "code_execution",
        )
    )
    code_tool_used = code_auth is not None and code_auth.used_calls > 0
    code_tool_call_count = code_auth.used_calls if code_auth else 0
    return {"id": turn.id, "session_id": turn.session_id, "ordinal": turn.ordinal, "attempt_number": turn.attempt_number, "status": turn.status, "question": turn.question, "scope": turn.scope, "section_id": turn.section_id, "lesson_id": turn.lesson_id, "lesson_version_id": turn.lesson_version_id, "answer_blocks": turn.answer_blocks, "citations": citations, "error_code": turn.error_code, "error_message": turn.error_message, "created_at": turn.created_at.isoformat(), "completed_at": turn.completed_at.isoformat() if turn.completed_at else None, "memory_count": memory_count, "completion_count": completion_count, "teaching_skill": _teaching_skill_projection(turn), "science_tool_used": science_tool_used, "science_tool_call_count": science_tool_call_count, "code_tool_used": code_tool_used, "code_tool_call_count": code_tool_call_count}


def cancel_turn(db: Session, workspace_id: str, turn_id: str) -> TutorTurn | None:
    workspace = db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")
        .with_for_update()
    )
    if not workspace:
        return None
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
    workspace = db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")
        .with_for_update()
    )
    if not workspace:
        return None
    original = db.scalar(
        select(TutorTurn)
        .where(TutorTurn.id == turn_id, TutorTurn.workspace_id == workspace_id)
        .with_for_update()
    )
    if not original:
        return None
    if original.status not in {"failed", "canceled", "queue_failed"}: raise ValueError("turn_not_retryable")
    session = db.scalar(
        select(TutorSession)
        .where(
            TutorSession.id == original.session_id,
            TutorSession.workspace_id == workspace_id,
            TutorSession.status == "active",
        )
        .with_for_update()
    )
    if not session: raise ValueError("session_not_active")
    active = db.scalar(select(TutorTurn.id).where(TutorTurn.session_id == session.id, TutorTurn.status.in_(ACTIVE_TURN_STATUSES)))
    if active:
        raise ValueError("active_turn_exists")
    retry = TutorTurn(session_id=session.id, workspace_id=workspace_id, ordinal=original.ordinal, attempt_number=original.attempt_number + 1, idempotency_key=str(uuid4()), status="queued", question=original.question, scope=original.scope, section_id=original.section_id, lesson_id=original.lesson_id, lesson_version_id=original.lesson_version_id, history_through_ordinal=original.history_through_ordinal, teaching_skill_id=original.teaching_skill_id, teaching_skill_version=original.teaching_skill_version, teaching_skill_hash=original.teaching_skill_hash)
    db.add(retry); db.flush()

    # Slice 4: Copy science tool authorization snapshot from original Turn to retry.
    # Per §3.5: retry copies the original authorization snapshot and remaining
    # budget (max_calls - used_calls), never expanding beyond the original max_calls.
    # New normal Turns do NOT inherit authorization.
    original_auth = db.scalar(
        select(TutorTurnToolAuthorization).where(
            TutorTurnToolAuthorization.turn_id == original.id,
            TutorTurnToolAuthorization.capability_id == "science_computation",
        )
    )
    if original_auth is not None:
        remaining_budget = max(0, original_auth.max_calls - original_auth.used_calls)
        retry_auth = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id=retry.id,
            workspace_id=workspace_id,
            capability_id=original_auth.capability_id,
            max_calls=remaining_budget,  # remaining budget, never expanding
            used_calls=0,
            mcp_server_name=original_auth.mcp_server_name,
            mcp_protocol_version=original_auth.mcp_protocol_version,
            mcp_tool_allowlist=original_auth.mcp_tool_allowlist,
            mcp_schema_hash=original_auth.mcp_schema_hash,
        )
        db.add(retry_auth)

    # Slice 4 packet 002: Copy code tool authorization from original Turn to retry.
    # Same pattern as science auth: remaining budget, never expanding.
    original_code_auth = db.scalar(
        select(TutorTurnToolAuthorization).where(
            TutorTurnToolAuthorization.turn_id == original.id,
            TutorTurnToolAuthorization.capability_id == "code_execution",
        )
    )
    if original_code_auth is not None:
        remaining_code_budget = max(0, original_code_auth.max_calls - original_code_auth.used_calls)
        retry_code_auth = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id=retry.id,
            workspace_id=workspace_id,
            capability_id=original_code_auth.capability_id,
            max_calls=remaining_code_budget,
            used_calls=0,
            mcp_server_name=original_code_auth.mcp_server_name,
            mcp_protocol_version=original_code_auth.mcp_protocol_version,
            mcp_tool_allowlist=original_code_auth.mcp_tool_allowlist,
            mcp_schema_hash=original_code_auth.mcp_schema_hash,
        )
        db.add(retry_code_auth)
        retry.code_tool_authorized = True

    db.commit(); db.refresh(retry)
    try: enqueue_tutor_turn(settings, retry.id)
    except Exception:
        retry.status = "queue_failed"; retry.error_code = "queue_unavailable"; retry.error_message = "Tutor 队列暂时不可用"; db.commit()
    return retry


def delete_turn(db: Session, workspace_id: str, turn_id: str) -> bool:
    """Hard-delete one terminal Tutor Turn and all of its private trace data.

    Session ordinals remain monotonic. A deleted Turn simply disappears from
    future history queries; renumbering would break idempotency and retry
    identity. Refuse deletion while any Turn in the Session is active so an
    in-flight provider cannot have already consumed content that the user just
    removed.
    """
    workspace = db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id, Workspace.lifecycle_status == "active")
        .with_for_update()
    )
    if not workspace:
        return False
    turn = db.scalar(
        select(TutorTurn)
        .where(TutorTurn.id == turn_id, TutorTurn.workspace_id == workspace_id)
        .with_for_update()
    )
    if not turn:
        return False
    session = db.scalar(
        select(TutorSession)
        .where(
            TutorSession.id == turn.session_id,
            TutorSession.workspace_id == workspace_id,
            TutorSession.status == "active",
        )
        .with_for_update()
    )
    if not session:
        return False
    if turn.status in ACTIVE_TURN_STATUSES:
        raise ValueError("turn_active")
    active_sibling = db.scalar(
        select(TutorTurn.id).where(
            TutorTurn.session_id == session.id,
            TutorTurn.status.in_(ACTIVE_TURN_STATUSES),
        )
    )
    if active_sibling:
        raise ValueError("active_turn_exists")

    run_ids = select(AgentRun.id).where(AgentRun.tutor_turn_id == turn.id)
    db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
    db.execute(delete(AgentRun).where(AgentRun.tutor_turn_id == turn.id))
    db.execute(delete(TutorTurnCitation).where(TutorTurnCitation.turn_id == turn.id))
    # Slice 4: Delete science tool authorization and code run associations
    db.execute(delete(TutorTurnToolAuthorization).where(TutorTurnToolAuthorization.turn_id == turn.id))
    db.execute(delete(TutorTurnCodeRun).where(TutorTurnCodeRun.turn_id == turn.id))
    db.delete(turn)
    db.commit()
    return True


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

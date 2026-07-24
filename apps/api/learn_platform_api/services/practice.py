"""Practice orchestration: jobs, safe projections, attempts, grading dispatch, deletion.

All queries are workspace-scoped. Pre-submission reads never expose the hidden
grading material (correct option, option rationales, rubric, reference answer).
Single-choice is graded deterministically in one transaction; short-answer
creates an immutable attempt and a grading job. Deletion follows ADR 001.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    Course,
    CourseGenerationJob,
    CourseVersionSource,
    DocumentChunk,
    Lesson,
    LessonVersion,
    JobToolAuthorization,
    PracticeAttempt,
    PracticeFeedback,
    PracticeItem,
    PracticeItemCitation,
    PracticeItemTarget,
    PracticeJob,
    PracticeJobSource,
    PracticeSet,
    SourceDocument,
    Workspace,
)
from learn_platform_api.services.practice_generation import execute_generation, execute_grading
from learn_platform_api.services.queue import enqueue_practice_job, enqueue_practice_set_deletion
from learn_platform_api.settings import Settings
from academic_companion.practice_agents import (
    ARTIFACT_CONTRACT_V1,
    ARTIFACT_CONTRACT_V2,
    CURRENT_ARTIFACT_CONTRACT,
    HARNESS_V2,
)

ACTIVE_JOB_STATUSES = {"queued", "running", "retry_wait", "cancel_requested"}
GRADEABLE_STATES = {"grading", "retry_wait", "queue_failed", "failed", "cancel_requested", "canceled"}
SHORT_ANSWER_MAX_CHARS = 8000


def _try_project_learning(db: Session, workspace_id: str, attempt: PracticeAttempt, feedback: PracticeFeedback, item: PracticeItem) -> None:
    """Learning projection within the same transaction as Feedback.

    Per ADR 003 §Transaction: Feedback, Learning Event, Signal and target
    recompute must commit atomically. This is NOT best-effort — if projection
    fails, the entire transaction (including Feedback) must roll back.
    """
    from learn_platform_api.services.learning import ensure_targets_for_lesson_version, ensure_item_target_mapping
    from learn_platform_api.services.learning_projection import project_attempt_feedback
    ps = db.get(PracticeSet, item.practice_set_id)
    if ps is None:
        return
    lv = db.get(LessonVersion, ps.lesson_version_id)
    if lv is None:
        return
    ensure_targets_for_lesson_version(db, workspace_id, ps.course_id, ps.course_version_id, ps.lesson_id, ps.lesson_version_id, lv.learning_objectives)
    ensure_item_target_mapping(db, item)
    project_attempt_feedback(db, workspace_id, attempt, feedback)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact_version_for_item(db: Session, item: PracticeItem) -> str:
    """Snapshot the artifact contract version a grading Job must keep.

    Per ADR 007 §3.1 the grader dispatches by the item's own harness version,
    but the Job still pins the contract family at submission so retry/reconciler
    cannot silently change it. Prefer the Set's pinned version; fall back to the
    coding harness version; otherwise read as v1 (historical items).
    """
    practice_set = db.get(PracticeSet, item.practice_set_id)
    if practice_set is not None:
        pinned = (practice_set.generation_config or {}).get("artifact_contract_version")
        if pinned:
            return pinned
    if item.item_type == "coding":
        harness = (item.answer_spec or {}).get("harness_version")
        if harness == HARNESS_V2:
            return ARTIFACT_CONTRACT_V2
    return ARTIFACT_CONTRACT_V1


# --------------------------------------------------------------------------- #
# Ownership validation
# --------------------------------------------------------------------------- #

def _resolve_lesson_version(db: Session, workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str) -> tuple[Course, Lesson, LessonVersion]:
    course = db.get(Course, course_id)
    version = db.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == course_version_id))  # existence probe
    if course is None or course.workspace_id != workspace_id or course.lifecycle_status != "active":
        raise LookupError("not_found")
    if course.current_active_version_id != course_version_id or version is None:
        raise ValueError("course_version_inactive")
    lesson = db.get(Lesson, lesson_id)
    lesson_version = db.get(LessonVersion, lesson_version_id)
    if (
        lesson is None or lesson_version is None
        or lesson.workspace_id != workspace_id
        or lesson.course_version_id != course_version_id
        or lesson_version.lesson_id != lesson.id
        or lesson_version.course_version_id != course_version_id
        or lesson_version.status != "published"
        or lesson.current_published_version_id != lesson_version.id
    ):
        raise ValueError("lesson_version_mismatch")
    return course, lesson, lesson_version


def _source_degraded(db: Session, course_version_id: str | None) -> bool:
    if not course_version_id:
        return False
    sources = list(db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == course_version_id)))
    if not sources:
        return True
    from learn_platform_api.db.models import DocumentVersion
    for source in sources:
        document = db.get(SourceDocument, source.document_id)
        version = db.get(DocumentVersion, source.document_version_id)
        if document is None or version is None or document.lifecycle_status != "active" or document.current_version_id != version.id or version.processing_status != "ready":
            return True
    return False


# --------------------------------------------------------------------------- #
# Generation jobs
# --------------------------------------------------------------------------- #

def _lesson_language(db: Session, lesson_id: str) -> str:
    job = db.scalar(
        select(CourseGenerationJob)
        .where(CourseGenerationJob.lesson_id == lesson_id, CourseGenerationJob.job_type == "lesson_draft")
        .order_by(CourseGenerationJob.created_at.desc())
    )
    return job.output_language if job and job.output_language in {"zh-CN", "en"} else "zh-CN"


def _existing_idempotent_job(db: Session, workspace_id: str, idempotency_key: str) -> PracticeJob | None:
    """Existence probe for the (workspace_id, idempotency_key) unique key.

    Kept as an injectable helper so tests can simulate the race window where a
    concurrent insert lands between this check and the commit; the surrounding
    ``IntegrityError`` handler converts that collision without leaking it.
    """
    return db.scalar(select(PracticeJob).where(PracticeJob.workspace_id == workspace_id, PracticeJob.idempotency_key == idempotency_key))


def create_generation_job(db: Session, settings: Settings, workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str, payload, idempotency_key: str) -> PracticeJob:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.lifecycle_status != "active":
        raise LookupError("not_found")
    _resolve_lesson_version(db, workspace_id, course_id, course_version_id, lesson_id, lesson_version_id)
    if _source_degraded(db, course_version_id):
        raise ValueError("source_snapshot_stale")
    output_language = payload.output_language or _lesson_language(db, lesson_id)
    legacy_request_hash = _hash(f"{course_version_id}|{lesson_version_id}|{payload.item_count}|{payload.difficulty}|{output_language}|{getattr(payload, 'item_type_mode', 'auto')}|{getattr(payload, 'code_languages', None)}")
    request_hash = _hash(f"{course_version_id}|{lesson_version_id}|{payload.item_count}|{payload.difficulty}|{output_language}|{getattr(payload, 'item_type_mode', 'auto')}|{getattr(payload, 'code_languages', None)}|{getattr(payload, 'code_tool_authorized', False)}|{getattr(payload, 'science_tool_authorized', False)}|{CURRENT_ARTIFACT_CONTRACT}")
    compatible_hashes = {request_hash}
    if not getattr(payload, "code_tool_authorized", False) and not getattr(payload, "science_tool_authorized", False):
        compatible_hashes.add(legacy_request_hash)
        if getattr(payload, "item_type_mode", "auto") == "auto" and getattr(payload, "code_languages", None) is None:
            compatible_hashes.add(_hash(f"{course_version_id}|{lesson_version_id}|{payload.item_count}|{payload.difficulty}|{output_language}"))
    existing = _existing_idempotent_job(db, workspace_id, idempotency_key)
    if existing:
        if existing.request_hash not in compatible_hashes:
            raise ValueError("idempotency_key_conflict")
        return existing
    active = db.scalar(select(PracticeJob.id).where(
        PracticeJob.workspace_id == workspace_id, PracticeJob.lesson_version_id == lesson_version_id,
        PracticeJob.job_type == "generate_set", PracticeJob.status.in_(ACTIVE_JOB_STATUSES),
    ))
    if active:
        raise ValueError("practice_generation_active")
    try:
        job = PracticeJob(
            workspace_id=workspace_id, job_type="generate_set", course_id=course_id, course_version_id=course_version_id,
            lesson_id=lesson_id, lesson_version_id=lesson_version_id, output_language=output_language, difficulty=payload.difficulty,
            item_count=payload.item_count, request_hash=request_hash, status="queued", idempotency_key=idempotency_key,
            attempt_count=0, external_processing_ack_at=_now(),
            item_type_mode=getattr(payload, 'item_type_mode', 'auto'),
            code_languages=getattr(payload, 'code_languages', None),
            artifact_contract_version=CURRENT_ARTIFACT_CONTRACT,
        )
        db.add(job)
        db.flush()
        from learn_platform_api.services.readiness import _read_capability_projection
        requested_capabilities = (
            ("code_execution", getattr(payload, "code_tool_authorized", False), ["run_code"], settings.practice_generation_max_tool_calls),
            ("science_computation", getattr(payload, "science_tool_authorized", False), ["WolframAlpha", "WolframContext"], settings.practice_generation_max_tool_calls),
        )
        for capability_id, authorized, allowlist, max_calls in requested_capabilities:
            if not authorized:
                continue
            projection = _read_capability_projection(db, capability_id)
            if not projection or not projection.get("ok"):
                raise ValueError(f"{capability_id}_unavailable")
            db.add(JobToolAuthorization(
                workspace_id=workspace_id,
                capability_id=capability_id,
                practice_job_id=job.id,
                max_calls=max_calls,
                used_calls=0,
                server_allowlist=json.dumps(allowlist),
                schema_hash_snapshot=projection.get("verified_schema_hash") or "",
                protocol_version_snapshot="2025-11-25",
            ))
        for source in db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == course_version_id)):
            db.add(PracticeJobSource(practice_job_id=job.id, workspace_id=workspace_id, document_id=source.document_id, document_version_id=source.document_version_id))
        db.commit()
        db.refresh(job)
    except IntegrityError:
        # Concurrent insert raced past the existence check on the
        # (workspace_id, idempotency_key) unique constraint. Convert it to the
        # normal idempotent/conflict behavior instead of leaking the DB error.
        db.rollback()
        existing = db.scalar(select(PracticeJob).where(PracticeJob.workspace_id == workspace_id, PracticeJob.idempotency_key == idempotency_key))
        if existing and existing.request_hash in compatible_hashes:
            return existing
        raise ValueError("idempotency_key_conflict")
    try:
        enqueue_practice_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_unavailable"; job.error_message = "练习生成队列暂时不可用"; db.commit()
    return job


def list_sets(db: Session, workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str) -> list[dict]:
    sets = list(db.scalars(select(PracticeSet).where(
        PracticeSet.workspace_id == workspace_id, PracticeSet.course_id == course_id,
        PracticeSet.course_version_id == course_version_id, PracticeSet.lesson_id == lesson_id,
        PracticeSet.lesson_version_id == lesson_version_id, PracticeSet.lifecycle_status == "active",
    ).order_by(PracticeSet.created_at.desc())))
    return [_set_list_item(db, item) for item in sets]


def get_set(db: Session, workspace_id: str, set_id: str) -> dict | None:
    practice_set = db.scalar(select(PracticeSet).where(PracticeSet.id == set_id, PracticeSet.workspace_id == workspace_id, PracticeSet.lifecycle_status == "active"))
    if practice_set is None:
        return None
    return _set_read(db, practice_set)


def _set_list_item(db: Session, practice_set: PracticeSet) -> dict:
    job = db.scalar(select(PracticeJob).where(PracticeJob.practice_set_id == practice_set.id).order_by(PracticeJob.created_at.desc()))
    return {
        "id": practice_set.id, "lesson_version_id": practice_set.lesson_version_id, "output_language": practice_set.output_language,
        "difficulty": practice_set.difficulty, "item_count": practice_set.item_count, "lifecycle_status": practice_set.lifecycle_status,
        "source_degraded": _source_degraded(db, practice_set.course_version_id), "created_at": practice_set.created_at.isoformat(),
        "latest_job": _job_dict(job),
    }


def _set_read(db: Session, practice_set: PracticeSet) -> dict:
    items = list(db.scalars(select(PracticeItem).where(PracticeItem.practice_set_id == practice_set.id).order_by(PracticeItem.ordinal)))
    return {
        "id": practice_set.id, "workspace_id": practice_set.workspace_id, "course_id": practice_set.course_id,
        "lesson_id": practice_set.lesson_id, "lesson_version_id": practice_set.lesson_version_id, "output_language": practice_set.output_language,
        "difficulty": practice_set.difficulty, "item_count": practice_set.item_count, "lifecycle_status": practice_set.lifecycle_status,
        "source_degraded": _source_degraded(db, practice_set.course_version_id), "created_at": practice_set.created_at.isoformat(),
        "items": [_item_read(db, item) for item in items],
    }


def _item_read(db: Session, item: PracticeItem) -> dict:
    options = [{"option_key": option["option_key"], "text": option["text"]} for option in item.options] if item.options else None
    # Slice 4 packet 002: include interaction_spec for coding items (public interface only)
    interaction_spec = getattr(item, 'interaction_spec', None)
    return {
        "id": item.id, "ordinal": item.ordinal, "item_type": item.item_type, "stem": item.stem,
        "options": options, "citations": _item_citations(db, item.id),
        "interaction_spec": interaction_spec,
    }


def _item_citations(db: Session, item_id: str) -> list[dict]:
    rows = list(db.execute(
        select(PracticeItemCitation, DocumentChunk, SourceDocument)
        .join(DocumentChunk, PracticeItemCitation.document_chunk_id == DocumentChunk.id)
        .join(SourceDocument, PracticeItemCitation.document_id == SourceDocument.id)
        .where(PracticeItemCitation.practice_item_id == item_id)
    ).all())
    result = []
    for citation, chunk, document in rows:
        available = document.lifecycle_status == "active" and document.current_version_id == citation.document_version_id
        result.append({
            "citation_key": citation.citation_key, "document_name": document.display_name,
            "heading_path": (chunk.heading_path or "").split(" / ") if chunk.heading_path else [],
            "page_start": chunk.page_start, "page_end": chunk.page_end, "available": available,
        })
    return result


def _job_dict(job: PracticeJob | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.id, "job_type": job.job_type, "practice_set_id": job.practice_set_id, "practice_attempt_id": job.practice_attempt_id,
        "status": job.status, "attempt_count": job.attempt_count, "error_code": job.error_code, "error_message": job.error_message,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Attempts and grading
# --------------------------------------------------------------------------- #

def _get_item(db: Session, workspace_id: str, item_id: str) -> tuple[PracticeItem, PracticeSet] | None:
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id, PracticeItem.workspace_id == workspace_id))
    if item is None:
        return None
    practice_set = db.get(PracticeSet, item.practice_set_id)
    if practice_set is None or practice_set.workspace_id != workspace_id or practice_set.lifecycle_status != "active":
        return None
    return item, practice_set


def submit_attempt(db: Session, settings: Settings, workspace_id: str, item_id: str, payload, idempotency_key: str) -> PracticeAttempt:
    resolved = _get_item(db, workspace_id, item_id)
    if resolved is None:
        raise LookupError("not_found")
    item, practice_set = resolved
    if _source_degraded(db, practice_set.course_version_id):
        raise ValueError("source_snapshot_stale")
    answer_key = (item.id, payload.option_key, payload.text, getattr(payload, 'source_code', None), getattr(payload, "science_tool_authorized", False))
    existing = db.scalar(select(PracticeAttempt).where(PracticeAttempt.practice_item_id == item.id, PracticeAttempt.idempotency_key == idempotency_key))
    if existing:
        if (existing.practice_item_id, existing.answer_payload.get("option_key"), existing.answer_payload.get("text"), existing.source_code, bool(existing.answer_payload.get("science_tool_authorized"))) != answer_key:
            raise ValueError("idempotency_key_conflict")
        return existing
    ordinal = (db.scalar(select(func.max(PracticeAttempt.ordinal)).where(PracticeAttempt.practice_item_id == item.id)) or 0) + 1
    try:
        if item.item_type == "single_choice":
            return _submit_single_choice(db, workspace_id, item, payload, idempotency_key, ordinal)
        if item.item_type == "coding":
            return _submit_coding(db, settings, workspace_id, item, payload, idempotency_key, ordinal)
        return _submit_short_answer(db, settings, workspace_id, item, payload, idempotency_key, ordinal)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(PracticeAttempt).where(
            PracticeAttempt.practice_item_id == item.id,
            PracticeAttempt.idempotency_key == idempotency_key,
        ))
        if existing and (existing.practice_item_id, existing.answer_payload.get("option_key"), existing.answer_payload.get("text"), existing.source_code, bool(existing.answer_payload.get("science_tool_authorized"))) == answer_key:
            return existing
        raise ValueError("idempotency_key_conflict")


def _submit_single_choice(db: Session, workspace_id: str, item: PracticeItem, payload, idempotency_key: str, ordinal: int) -> PracticeAttempt:
    valid_keys = {option["option_key"] for option in item.options or []}
    if payload.option_key not in valid_keys:
        raise ValueError("invalid_answer")
    attempt = PracticeAttempt(
        workspace_id=workspace_id, practice_item_id=item.id, ordinal=ordinal, item_type="single_choice",
        answer_payload={"option_key": payload.option_key}, idempotency_key=idempotency_key, status="succeeded",
        completed_at=_now(),
    )
    db.add(attempt)
    db.flush()
    feedback = _build_single_choice_feedback(item, payload.option_key)
    fb = PracticeFeedback(
        practice_attempt_id=attempt.id, workspace_id=workspace_id, verdict=feedback["verdict"], score=feedback["score"],
        criterion_results=None, feedback_blocks=feedback["blocks"], is_ai_graded=0, created_at=_now(),
    )
    db.add(fb)
    db.flush()
    _try_project_learning(db, workspace_id, attempt, fb, item)
    db.commit()
    db.refresh(attempt)
    return attempt


def _build_single_choice_feedback(item: PracticeItem, selected_key: str) -> dict:
    spec = item.answer_spec
    correct_key = spec.get("correct_option_key")
    rationales = spec.get("option_rationales", {})
    option_text = {option["option_key"]: option["text"] for option in item.options or []}
    correct = selected_key == correct_key
    blocks = [{
        "block_key": "your_choice", "type": "explanation",
        "text": f"你的选择：{option_text.get(selected_key, selected_key)}", "citation_ids": [], "option_key": selected_key,
    }]
    correct_rationale = rationales.get(correct_key, {})
    blocks.append({
        "block_key": "correct_answer", "type": "reference",
        "text": f"正确答案：{option_text.get(correct_key, correct_key)}。{correct_rationale.get('rationale', '')}",
        "citation_ids": correct_rationale.get("citation_ids", []), "option_key": correct_key,
    })
    if not correct:
        wrong_rationale = rationales.get(selected_key, {})
        blocks.append({
            "block_key": "why_wrong", "type": "improvement",
            "text": f"{option_text.get(selected_key, selected_key)} 不正确：{wrong_rationale.get('rationale', '')}",
            "citation_ids": wrong_rationale.get("citation_ids", []), "option_key": selected_key,
        })
    return {"verdict": "correct" if correct else "incorrect", "score": 100 if correct else 0, "blocks": blocks}


def _submit_short_answer(db: Session, settings: Settings, workspace_id: str, item: PracticeItem, payload, idempotency_key: str, ordinal: int) -> PracticeAttempt:
    if not payload.external_processing_ack:
        raise ValueError("external_processing_required")
    text = (payload.text or "")
    if len(text) > SHORT_ANSWER_MAX_CHARS:
        raise ValueError("answer_too_large")
    attempt = PracticeAttempt(
        workspace_id=workspace_id, practice_item_id=item.id, ordinal=ordinal, item_type=item.item_type,
        answer_payload={"text": text, "science_tool_authorized": bool(getattr(payload, "science_tool_authorized", False))}, idempotency_key=idempotency_key, status="grading",
        external_processing_ack_at=_now(),
    )
    db.add(attempt)
    db.flush()
    job = PracticeJob(
        workspace_id=workspace_id, job_type="grade_attempt", practice_attempt_id=attempt.id,
        output_language=item.item_type and "zh-CN", difficulty="standard", item_count=1,
        request_hash=_hash(f"grade|{attempt.id}"), status="queued", idempotency_key=f"grade-{attempt.id}",
        attempt_count=0, external_processing_ack_at=_now(),
        artifact_contract_version=_artifact_version_for_item(db, item),
    )
    # Preserve the item's language on the grading job for consistent feedback.
    practice_set = db.get(PracticeSet, item.practice_set_id)
    job.output_language = practice_set.output_language if practice_set else "zh-CN"
    db.add(job)
    db.flush()
    if item.item_type == "scientific" and getattr(payload, "science_tool_authorized", False):
        from learn_platform_api.services.readiness import _read_capability_projection
        projection = _read_capability_projection(db, "science_computation")
        if projection and projection.get("ok"):
            db.add(JobToolAuthorization(
                workspace_id=workspace_id,
                capability_id="science_computation",
                practice_job_id=job.id,
                max_calls=settings.practice_grading_max_science_calls,
                used_calls=0,
                server_allowlist=json.dumps(["WolframAlpha", "WolframContext"]),
                schema_hash_snapshot=projection.get("verified_schema_hash") or "",
                protocol_version_snapshot="2025-11-25",
            ))
    attempt.practice_job_id = job.id
    db.commit()
    db.refresh(attempt)
    try:
        enqueue_practice_job(settings, job.id)
    except Exception:
        attempt.status = "queue_failed"; attempt.error_code = "queue_unavailable"; attempt.error_message = "评分队列暂时不可用"
        job.status = "queue_failed"; job.error_code = "queue_unavailable"
        db.commit()
    return attempt


SOURCE_CODE_MAX_CHARS = 20_000  # Per MCP contract SOURCE_CODE_MAX_CHARS


def _submit_coding(db: Session, settings: Settings, workspace_id: str, item: PracticeItem, payload, idempotency_key: str, ordinal: int) -> PracticeAttempt:
    """Submit a coding attempt with source_code.

    Per Spec 004 §6.3: the attempt carries source_code which will be
    graded deterministically via MCP execution against the item's
    hidden tests. The grading job is enqueued same as short_answer.
    """
    if not payload.external_processing_ack:
        raise ValueError("external_processing_required")
    source_code = (getattr(payload, 'source_code', None) or "")
    if not source_code.strip():
        raise ValueError("source_code_required")
    if len(source_code) > SOURCE_CODE_MAX_CHARS:
        raise ValueError("source_code_too_large")
    attempt = PracticeAttempt(
        workspace_id=workspace_id, practice_item_id=item.id, ordinal=ordinal, item_type="coding",
        answer_payload={"source_code_hash": _hash(source_code)}, source_code=source_code,
        idempotency_key=idempotency_key, status="grading",
        external_processing_ack_at=_now(),
    )
    db.add(attempt)
    db.flush()
    job = PracticeJob(
        workspace_id=workspace_id, job_type="grade_attempt", practice_attempt_id=attempt.id,
        output_language="zh-CN", difficulty="standard", item_count=1,
        request_hash=_hash(f"grade|{attempt.id}"), status="queued", idempotency_key=f"grade-{attempt.id}",
        attempt_count=0, external_processing_ack_at=_now(),
        artifact_contract_version=_artifact_version_for_item(db, item),
    )
    # Preserve the item's language on the grading job for consistent feedback.
    practice_set = db.get(PracticeSet, item.practice_set_id)
    job.output_language = practice_set.output_language if practice_set else "zh-CN"
    db.add(job)
    db.flush()
    from learn_platform_api.services.readiness import _read_capability_projection
    projection = _read_capability_projection(db, "code_execution")
    if not projection or not projection.get("ok"):
        raise ValueError("code_execution_unavailable")
    db.add(JobToolAuthorization(
        workspace_id=workspace_id,
        capability_id="code_execution",
        practice_job_id=job.id,
        max_calls=1,
        used_calls=0,
        server_allowlist=json.dumps(["run_code"]),
        schema_hash_snapshot=projection.get("verified_schema_hash") or "",
        protocol_version_snapshot="2025-11-25",
    ))
    attempt.practice_job_id = job.id
    db.commit()
    db.refresh(attempt)
    try:
        enqueue_practice_job(settings, job.id)
    except Exception:
        attempt.status = "queue_failed"; attempt.error_code = "queue_unavailable"; attempt.error_message = "评分队列暂时不可用"
        job.status = "queue_failed"; job.error_code = "queue_unavailable"
        db.commit()
    return attempt


def list_attempts(db: Session, workspace_id: str, item_id: str) -> list[dict]:
    if _get_item(db, workspace_id, item_id) is None:
        return []
    attempts = list(db.scalars(select(PracticeAttempt).where(PracticeAttempt.practice_item_id == item_id).order_by(PracticeAttempt.ordinal.desc())))
    return [_attempt_read(db, attempt) for attempt in attempts]


def get_attempt(db: Session, workspace_id: str, attempt_id: str) -> dict | None:
    attempt = db.scalar(select(PracticeAttempt).where(PracticeAttempt.id == attempt_id, PracticeAttempt.workspace_id == workspace_id))
    if attempt is None:
        return None
    return _attempt_read(db, attempt)


def _attempt_read(db: Session, attempt: PracticeAttempt) -> dict:
    feedback = db.scalar(select(PracticeFeedback).where(PracticeFeedback.practice_attempt_id == attempt.id))
    return {
        "id": attempt.id, "practice_item_id": attempt.practice_item_id, "ordinal": attempt.ordinal, "item_type": attempt.item_type,
        "status": attempt.status, "option_key": attempt.answer_payload.get("option_key") if attempt.item_type == "single_choice" else None,
        "text": attempt.answer_payload.get("text") if attempt.item_type in {"short_answer", "scientific"} else None,
        "source_code": attempt.source_code if attempt.item_type == "coding" else None,
        "practice_job_id": attempt.practice_job_id, "error_code": attempt.error_code, "error_message": attempt.error_message,
        "created_at": attempt.created_at.isoformat(), "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "feedback": _feedback_read(db, attempt, feedback),
    }


def _feedback_read(db: Session, attempt: PracticeAttempt, feedback: PracticeFeedback | None) -> dict | None:
    if feedback is None:
        return None
    citations = _item_citations(db, attempt.practice_item_id)
    return {
        "verdict": feedback.verdict, "score": feedback.score, "is_ai_graded": bool(feedback.is_ai_graded),
        "criterion_results": feedback.criterion_results or [], "feedback_blocks": feedback.feedback_blocks, "citations": citations,
        # Slice 4 packet 002: coding execution summary
        "coding_tests_passed": getattr(feedback, 'coding_tests_passed', None),
        "coding_tests_total": getattr(feedback, 'coding_tests_total', None),
        "coding_error_categories": getattr(feedback, 'coding_error_categories', None),
        "coding_public_cases": getattr(feedback, 'coding_public_cases', None),
        "science_verification": _science_verification_read(db, attempt.practice_job_id, "VerifyScientificAttempt", "learner_final_result") if attempt.item_type == "scientific" else None,
    }


def _science_verification_read(db: Session, job_id: str | None, tool_name: str, purpose: str) -> dict:
    if not job_id:
        return {"used": False, "status": "not_used", "tool": None, "purpose": purpose, "checked_at": None}
    call = db.scalar(
        select(AgentToolCall)
        .join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id)
        .where(AgentRun.practice_job_id == job_id, AgentToolCall.tool_name == tool_name)
        .order_by(AgentToolCall.created_at.desc())
    )
    if call is None:
        return {"used": False, "status": "not_used", "tool": None, "purpose": purpose, "checked_at": None}
    return {
        "used": True,
        "status": "verified" if call.status == "succeeded" else "failed",
        "tool": "Wolfram",
        "purpose": purpose,
        "checked_at": call.created_at,
    }


# --------------------------------------------------------------------------- #
# Job lifecycle
# --------------------------------------------------------------------------- #

def get_job(db: Session, workspace_id: str, job_id: str) -> PracticeJob | None:
    return db.scalar(select(PracticeJob).where(PracticeJob.id == job_id, PracticeJob.workspace_id == workspace_id))


def cancel_job(db: Session, workspace_id: str, job_id: str) -> PracticeJob | None:
    job = db.scalar(select(PracticeJob).where(PracticeJob.id == job_id, PracticeJob.workspace_id == workspace_id).with_for_update())
    if job is None:
        return None
    if job.status in ACTIVE_JOB_STATUSES:
        job.status = "canceled" if job.status in {"queued", "queue_failed", "retry_wait"} else "cancel_requested"
        if job.status == "canceled":
            job.completed_at = _now()
            _mark_attempt_for_canceled_job(db, job)
        db.commit()
    return job


def retry_job(db: Session, settings: Settings, workspace_id: str, job_id: str) -> PracticeJob | None:
    job = db.scalar(select(PracticeJob).where(
        PracticeJob.id == job_id,
        PracticeJob.workspace_id == workspace_id,
    ).with_for_update())
    if job is None:
        return None
    if job.status not in {"failed", "canceled", "queue_failed"}:
        raise ValueError("job_not_retryable")
    if job.job_type == "grade_attempt":
        attempt = db.get(PracticeAttempt, job.practice_attempt_id)
        if attempt is None or attempt.status not in {"failed", "queue_failed", "canceled"}:
            raise ValueError("job_not_retryable")
        attempt.status = "grading"; attempt.error_code = None; attempt.error_message = None
    job.status = "queued"; job.error_code = None; job.error_message = None
    job.next_attempt_at = None; job.lease_expires_at = None; job.worker_id = None
    db.commit()
    try:
        enqueue_practice_job(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_unavailable"; job.error_message = "练习队列暂时不可用"
        if job.job_type == "grade_attempt":
            attempt = db.get(PracticeAttempt, job.practice_attempt_id)
            if attempt is not None:
                attempt.status = "queue_failed"; attempt.error_code = "queue_unavailable"
        db.commit()
    return job


def _mark_attempt_for_canceled_job(db: Session, job: PracticeJob) -> None:
    if job.job_type != "grade_attempt":
        return
    attempt = db.get(PracticeAttempt, job.practice_attempt_id)
    if attempt is not None and attempt.status in {"grading", "retry_wait", "queue_failed"}:
        attempt.status = "canceled"; attempt.completed_at = _now(); attempt.error_code = "practice_canceled"


# --------------------------------------------------------------------------- #
# Deletion
# --------------------------------------------------------------------------- #

def delete_set(db: Session, settings: Settings, workspace_id: str, set_id: str) -> bool:
    practice_set = db.scalar(select(PracticeSet).where(PracticeSet.id == set_id, PracticeSet.workspace_id == workspace_id, PracticeSet.lifecycle_status == "active").with_for_update())
    if practice_set is None:
        return False
    db.execute(
        PracticeJob.__table__.update().where(
            PracticeJob.workspace_id == workspace_id, PracticeJob.practice_set_id == set_id, PracticeJob.status.in_(ACTIVE_JOB_STATUSES)
        ).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None)
    )
    item_ids = select(PracticeItem.id).where(PracticeItem.practice_set_id == set_id)
    db.execute(
        PracticeJob.__table__.update().where(
            PracticeJob.workspace_id == workspace_id, PracticeJob.practice_attempt_id.in_(
                select(PracticeAttempt.id).where(PracticeAttempt.practice_item_id.in_(item_ids))
            ), PracticeJob.status.in_(ACTIVE_JOB_STATUSES)
        ).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None)
    )
    practice_set.lifecycle_status = "deleting"; practice_set.deleted_at = _now()
    db.commit()
    try:
        enqueue_practice_set_deletion(settings, set_id)
    except Exception:
        pass
    return True


def _disconnect_practice_cycle(db: Session, *, set_ids=None, attempt_ids=None, job_ids=None) -> None:
    """Null both sides of the PracticeJob <-> {PracticeSet, PracticeAttempt} cycle.

    Real Postgres enforces the foreign keys, so circular references must be
    dropped before either side is deleted. SQLite does not enforce them, which
    is exactly why this step cannot be skipped or left untested on Postgres.
    """
    if job_ids is not None:
        db.execute(update(PracticeJob).where(PracticeJob.id.in_(job_ids)).values(practice_set_id=None, practice_attempt_id=None))
    if attempt_ids is not None:
        db.execute(update(PracticeAttempt).where(PracticeAttempt.id.in_(attempt_ids)).values(practice_job_id=None))
    if set_ids is not None:
        db.execute(update(PracticeSet).where(PracticeSet.id.in_(set_ids)).values(practice_job_id=None))
    db.flush()


def cleanup_set(db: Session, set_id: str) -> bool:
    practice_set = db.scalar(select(PracticeSet).where(PracticeSet.id == set_id, PracticeSet.lifecycle_status == "deleting").with_for_update())
    if practice_set is None:
        return False
    workspace_id = practice_set.workspace_id
    # Materialize every id range BEFORE disconnecting, because the job filter
    # (practice_set_id / practice_attempt_id) is exactly what the disconnect nulls.
    item_ids = [row[0] for row in db.execute(select(PracticeItem.id).where(PracticeItem.practice_set_id == set_id)).all()]
    attempt_ids = [row[0] for row in db.execute(select(PracticeAttempt.id).where(PracticeAttempt.practice_item_id.in_(item_ids))).all()] if item_ids else []
    job_ids = [row[0] for row in db.execute(select(PracticeJob.id).where(
        PracticeJob.workspace_id == workspace_id,
        (PracticeJob.practice_set_id == set_id) | (PracticeJob.practice_attempt_id.in_(attempt_ids) if attempt_ids else False),
    )).all()]
    run_ids = [row[0] for row in db.execute(select(AgentRun.id).where(AgentRun.practice_job_id.in_(job_ids))).all()] if job_ids else []

    # §4: Delete learning facts FIRST — learning_events FK to attempts/feedback.
    affected_targets: set[str] = set()
    from learn_platform_api.services.learning_projection import delete_set_learning_facts, _recompute_target
    if item_ids:
        affected_targets = delete_set_learning_facts(db, workspace_id, item_ids)

    _disconnect_practice_cycle(db, set_ids={set_id}, attempt_ids=attempt_ids, job_ids=job_ids)
    if run_ids:
        db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
    if job_ids:
        db.execute(delete(AgentRun).where(AgentRun.practice_job_id.in_(job_ids)))
    if attempt_ids:
        db.execute(delete(PracticeFeedback).where(PracticeFeedback.practice_attempt_id.in_(attempt_ids)))
        db.execute(delete(PracticeAttempt).where(PracticeAttempt.id.in_(attempt_ids)))
    if item_ids:
        db.execute(delete(PracticeItemCitation).where(PracticeItemCitation.practice_item_id.in_(item_ids)))
        db.execute(delete(PracticeItemTarget).where(PracticeItemTarget.practice_item_id.in_(item_ids)))
    db.execute(delete(PracticeItem).where(PracticeItem.practice_set_id == set_id))
    if job_ids:
        db.execute(delete(PracticeJobSource).where(PracticeJobSource.practice_job_id.in_(job_ids)))
        db.execute(delete(JobToolAuthorization).where(JobToolAuthorization.practice_job_id.in_(job_ids)))
        db.execute(delete(PracticeJob).where(PracticeJob.id.in_(job_ids)))
    db.delete(practice_set)
    db.flush()
    # Deletion and projection remain atomic.
    for tid in affected_targets:
        _recompute_target(db, tid, workspace_id)
    db.commit()
    return True


def delete_attempt(db: Session, settings: Settings, workspace_id: str, attempt_id: str) -> bool:
    attempt = db.scalar(select(PracticeAttempt).where(PracticeAttempt.id == attempt_id, PracticeAttempt.workspace_id == workspace_id).with_for_update())
    if attempt is None:
        return False
    grade_job_id = attempt.practice_job_id
    # Cancel any in-flight grading job before removing the attempt so a late
    # worker cannot resurrect feedback for an attempt the user deleted.
    if grade_job_id:
        db.execute(update(PracticeJob).where(PracticeJob.id == grade_job_id, PracticeJob.status.in_(ACTIVE_JOB_STATUSES)).values(status="cancel_requested", lease_expires_at=None, next_attempt_at=None))
    # §4: Delete learning facts FIRST — they have FKs to Attempt/Feedback.
    affected_targets: set[str] = set()
    from learn_platform_api.services.learning_projection import delete_attempt_learning_facts, _recompute_target
    affected_targets = delete_attempt_learning_facts(db, workspace_id, attempt_id, None)
    # Delete trace.
    run_ids = select(AgentRun.id).where(AgentRun.practice_job_id == grade_job_id) if grade_job_id else []
    if grade_job_id:
        db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
        db.execute(delete(AgentRun).where(AgentRun.practice_job_id == grade_job_id))
    db.execute(delete(PracticeFeedback).where(PracticeFeedback.practice_attempt_id == attempt_id))
    # Disconnect the attempt <-> job cycle before deleting either side.
    _disconnect_practice_cycle(db, attempt_ids=[attempt_id], job_ids=[grade_job_id] if grade_job_id else None)
    if grade_job_id:
        db.execute(delete(PracticeJobSource).where(PracticeJobSource.practice_job_id == grade_job_id))
        db.execute(delete(JobToolAuthorization).where(JobToolAuthorization.practice_job_id == grade_job_id))
        db.execute(delete(PracticeJob).where(PracticeJob.id == grade_job_id))
    db.delete(attempt)
    db.flush()
    # Deletion and projection remain atomic.
    for tid in affected_targets:
        _recompute_target(db, tid, workspace_id)
    db.commit()
    return True


def delete_sets_for_course(db: Session, settings: Settings, workspace_id: str, course_id: str) -> None:
    """Hide and schedule cleanup of every practice set belonging to a course.

    Used when a course is deleted so that practice derived facts do not survive
    the course while remaining readable through stale references.
    """
    sets = list(db.scalars(select(PracticeSet).where(
        PracticeSet.workspace_id == workspace_id, PracticeSet.course_id == course_id, PracticeSet.lifecycle_status == "active",
    )))
    for practice_set in sets:
        delete_set(db, settings, workspace_id, practice_set.id)


def hard_delete_workspace_practice(db: Session, workspace_id: str) -> None:
    """Hard-delete all practice facts for a workspace (used by workspace deletion)."""
    item_ids = select(PracticeItem.id).where(PracticeItem.workspace_id == workspace_id)
    attempt_ids = select(PracticeAttempt.id).where(PracticeAttempt.workspace_id == workspace_id)
    job_ids = select(PracticeJob.id).where(PracticeJob.workspace_id == workspace_id)
    set_ids = select(PracticeSet.id).where(PracticeSet.workspace_id == workspace_id)
    run_ids = select(AgentRun.id).where(AgentRun.practice_job_id.in_(job_ids))
    # Drop the full PracticeJob <-> {PracticeSet, PracticeAttempt} cycle first.
    _disconnect_practice_cycle(db, set_ids=set_ids, attempt_ids=attempt_ids, job_ids=job_ids)
    db.execute(delete(AgentToolCall).where(AgentToolCall.agent_run_id.in_(run_ids)))
    db.execute(delete(AgentRun).where(AgentRun.practice_job_id.in_(job_ids)))
    db.execute(delete(PracticeFeedback).where(PracticeFeedback.workspace_id == workspace_id))
    db.execute(delete(PracticeAttempt).where(PracticeAttempt.workspace_id == workspace_id))
    db.execute(delete(PracticeItemCitation).where(PracticeItemCitation.practice_item_id.in_(item_ids)))
    db.execute(delete(PracticeItem).where(PracticeItem.workspace_id == workspace_id))
    db.execute(delete(PracticeJobSource).where(PracticeJobSource.workspace_id == workspace_id))
    db.execute(delete(JobToolAuthorization).where(JobToolAuthorization.practice_job_id.in_(job_ids)))
    db.execute(delete(PracticeJob).where(PracticeJob.workspace_id == workspace_id))
    db.execute(delete(PracticeSet).where(PracticeSet.workspace_id == workspace_id))

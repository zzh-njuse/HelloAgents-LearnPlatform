"""Learning API service: safe projections, review actions, memory CRUD, policy, recompute.

All queries are workspace-scoped. Never returns projection_score, answers, rubric,
feedback text, prompts or evidence in any projection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    CourseVersionSource, DocumentVersion, LearningEvent, LearningMemory, LearningMemoryPolicy,
    LearningMemoryRevision, LearningMemorySource, LearningProjectionJob, LearningTarget, Lesson,
    MasterySignal, MasteryState, PracticeAttempt, PracticeFeedback, PracticeItem,
    PracticeItemTarget, PracticeSet, ReviewAction, ReviewItem, SourceDocument, Weakness,
    Workspace,
)
from learn_platform_api.settings import Settings

SNOOZE_DAYS = {1, 3, 7, 30}
REVIEW_VALIDATION_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _clean_text(value: str) -> str:
    result = value.strip()
    for _ in range(2):
        if not (len(result) >= 2 and result.startswith('"') and result.endswith('"')):
            break
        try:
            decoded = json.loads(result)
        except (TypeError, ValueError):
            break
        if not isinstance(decoded, str) or decoded == result:
            break
        result = decoded.strip()
    return result


def _target_title(db: Session, target: LearningTarget) -> str:
    if target.kind != "lesson_overall":
        return _clean_text(target.title)
    lesson = db.get(Lesson, target.lesson_id)
    return f"{_clean_text(lesson.title)}：整体理解" if lesson else "本课节：整体理解"


# --------------------------------------------------------------------------- #
# Target initialization
# --------------------------------------------------------------------------- #

def ensure_targets_for_lesson_version(db: Session, workspace_id: str, course_id: str, course_version_id: str, lesson_id: str, lesson_version_id: str, learning_objectives: list[str]) -> None:
    """Create stable learning targets from lesson objectives if they don't exist."""
    existing = db.scalar(select(func.count()).select_from(LearningTarget).where(LearningTarget.lesson_version_id == lesson_version_id))
    if existing and existing > 0:
        return
    for index, obj in enumerate(learning_objectives, 1):
        db.add(LearningTarget(
            workspace_id=workspace_id, course_id=course_id, course_version_id=course_version_id,
            lesson_id=lesson_id, lesson_version_id=lesson_version_id, target_key=f"objective_{index}",
            title=_clean_text(obj)[:300], kind="objective",
        ))
    db.add(LearningTarget(
        workspace_id=workspace_id, course_id=course_id, course_version_id=course_version_id,
        lesson_id=lesson_id, lesson_version_id=lesson_version_id, target_key="lesson_overall",
        title="本课节：整体理解", kind="lesson_overall",
    ))
    db.flush()


def ensure_item_target_mapping(db: Session, item: PracticeItem) -> None:
    """Map generated items to their declared target; old items fall back safely."""
    existing = db.scalar(select(PracticeItemTarget).where(PracticeItemTarget.practice_item_id == item.id))
    if existing is not None:
        return
    ps = db.get(PracticeSet, item.practice_set_id)
    if ps is None:
        return
    declared_key = (item.answer_spec or {}).get("_learning_target_key")
    target_key = declared_key or "lesson_overall"
    target = db.scalar(select(LearningTarget).where(
        LearningTarget.lesson_version_id == ps.lesson_version_id, LearningTarget.target_key == target_key,
    ))
    if declared_key and target is None:
        raise ValueError("invalid_learning_target")
    if target is None:
        return
    db.add(PracticeItemTarget(practice_item_id=item.id, learning_target_id=target.id, workspace_id=item.workspace_id, criterion_key=None))
    db.flush()


# --------------------------------------------------------------------------- #
# Safe projections for API
# --------------------------------------------------------------------------- #

def _target_source_degraded(db: Session, target: LearningTarget) -> bool:
    rows = list(db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == target.course_version_id)))
    if not rows:
        return True
    for src in rows:
        doc = db.get(SourceDocument, src.document_id)
        ver = db.get(DocumentVersion, src.document_version_id)
        if doc is None or ver is None or doc.lifecycle_status != "active" or doc.current_version_id != ver.id or ver.processing_status != "ready":
            return True
    return False


def list_learning_state(db: Session, workspace_id: str, *, course_id: str | None = None, lesson_id: str | None = None) -> dict:
    """Workspace/course/lesson mastery summary with safe band projections."""
    statement = select(LearningTarget, MasteryState).outerjoin(MasteryState, MasteryState.learning_target_id == LearningTarget.id).where(LearningTarget.workspace_id == workspace_id)
    if course_id:
        statement = statement.where(LearningTarget.course_id == course_id)
    if lesson_id:
        statement = statement.where(LearningTarget.lesson_id == lesson_id)
    rows = list(db.execute(statement).all())
    target_ids = [target.id for target, _state in rows]
    lesson_ids = {target.lesson_id for target, _state in rows}
    lessons = {lesson.id: lesson for lesson in db.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids)))} if lesson_ids else {}
    signal_counts: dict[tuple[str, bool], int] = {}
    if target_ids:
        for target_id, is_ai, count in db.execute(
            select(MasterySignal.learning_target_id, MasterySignal.is_ai_derived, func.count())
            .where(MasterySignal.learning_target_id.in_(target_ids))
            .group_by(MasterySignal.learning_target_id, MasterySignal.is_ai_derived)
        ):
            signal_counts[(target_id, bool(is_ai))] = int(count)
    weaknesses = {
        weakness.learning_target_id: weakness
        for weakness in db.scalars(select(Weakness).where(Weakness.learning_target_id.in_(target_ids)))
    } if target_ids else {}
    weakness_ids = [weakness.id for weakness in weaknesses.values()]
    reviews = {
        review.weakness_id: review
        for review in db.scalars(select(ReviewItem).where(ReviewItem.weakness_id.in_(weakness_ids)))
    } if weakness_ids else {}
    degraded_by_version: dict[str, bool] = {}
    targets = []
    band_counts = {"insufficient": 0, "needs_review": 0, "developing": 0, "secure": 0}
    for target, state in rows:
        band = state.band if state else "insufficient"
        band_counts[band] = band_counts.get(band, 0) + 1
        det_count = signal_counts.get((target.id, False), 0)
        ai_count = signal_counts.get((target.id, True), 0)
        weakness = weaknesses.get(target.id)
        review = reviews.get(weakness.id) if weakness else None
        if target.course_version_id not in degraded_by_version:
            degraded_by_version[target.course_version_id] = _target_source_degraded(db, target)
        target_title = _clean_text(target.title)
        if target.kind == "lesson_overall":
            lesson = lessons.get(target.lesson_id)
            target_title = f"{_clean_text(lesson.title)}：整体理解" if lesson else "本课节：整体理解"
        targets.append({
            "target_id": target.id, "target_title": target_title, "target_key": target.target_key,
            "band": band, "evidence_count": state.evidence_count if state else 0,
            "distinct_set_count": state.distinct_set_count if state else 0,
            "deterministic_signal_count": det_count, "ai_signal_count": ai_count,
            "last_evidence_at": state.last_evidence_at.isoformat() if state and state.last_evidence_at else None,
            "weakness_status": weakness.status if weakness else None,
            "review_status": review.status if review else None,
            "course_id": target.course_id, "lesson_id": target.lesson_id,
            "source_degraded": degraded_by_version[target.course_version_id],
        })
    return {"workspace_id": workspace_id, "summary": band_counts, "targets": targets}


def get_target_detail(db: Session, workspace_id: str, target_id: str) -> dict | None:
    target = db.scalar(select(LearningTarget).where(LearningTarget.id == target_id, LearningTarget.workspace_id == workspace_id))
    if target is None:
        return None
    state = db.scalar(select(MasteryState).where(
        MasteryState.learning_target_id == target_id,
        MasteryState.workspace_id == workspace_id,
    ))
    det_count = int(db.scalar(select(func.count()).select_from(MasterySignal).where(MasterySignal.learning_target_id == target_id, MasterySignal.is_ai_derived == 0)) or 0)
    ai_count = int(db.scalar(select(func.count()).select_from(MasterySignal).where(MasterySignal.learning_target_id == target_id, MasterySignal.is_ai_derived == 1)) or 0)
    weakness = db.scalar(select(Weakness).where(
        Weakness.learning_target_id == target_id,
        Weakness.workspace_id == workspace_id,
    ))
    review = db.scalar(select(ReviewItem).where(ReviewItem.weakness_id == weakness.id)) if weakness else None
    return {
        "target_id": target.id, "target_title": _target_title(db, target), "band": state.band if state else "insufficient",
        "evidence_count": state.evidence_count if state else 0,
        "deterministic_signal_count": det_count, "ai_signal_count": ai_count,
        "last_evidence_at": state.last_evidence_at.isoformat() if state and state.last_evidence_at else None,
        "weakness_status": weakness.status if weakness else None, "review_status": review.status if review else None,
    }


# --------------------------------------------------------------------------- #
# Review items
# --------------------------------------------------------------------------- #

def list_review_items(db: Session, workspace_id: str, *, status: str | None = None, course_id: str | None = None) -> list[dict]:
    statement = (select(ReviewItem, Weakness, LearningTarget)
                 .join(Weakness, ReviewItem.weakness_id == Weakness.id)
                 .join(LearningTarget, Weakness.learning_target_id == LearningTarget.id)
                 .where(ReviewItem.workspace_id == workspace_id))
    if status:
        statement = statement.where(ReviewItem.status == status)
    if course_id:
        statement = statement.where(LearningTarget.course_id == course_id)
    statement = statement.order_by(ReviewItem.due_at.asc().nulls_first(), Weakness.status.asc(), ReviewItem.updated_at.desc())
    items = []
    for ri, weakness, target in db.execute(statement).all():
        source = db.execute(
            select(LearningEvent, PracticeAttempt, PracticeItem, PracticeSet, MasterySignal)
            .join(PracticeAttempt, LearningEvent.practice_attempt_id == PracticeAttempt.id)
            .join(PracticeItem, PracticeAttempt.practice_item_id == PracticeItem.id)
            .join(PracticeSet, PracticeItem.practice_set_id == PracticeSet.id)
            .join(MasterySignal, (MasterySignal.learning_event_id == LearningEvent.id) & (MasterySignal.learning_target_id == target.id))
            .where(LearningEvent.id == weakness.last_negative_event_id)
        ).first()
        lesson = db.get(Lesson, target.lesson_id)
        items.append({
            "id": ri.id, "target_id": target.id, "target_key": target.target_key,
            "target_title": _target_title(db, target), "weakness_status": weakness.status,
            "status": ri.status, "due_at": ri.due_at.isoformat() if ri.due_at else None,
            "reopen_count": ri.reopen_count, "reason_snapshot": ri.reason_snapshot,
            "course_id": target.course_id, "lesson_id": target.lesson_id,
            "lesson_title": lesson.title if lesson else "",
            "source_attempt_id": source[1].id if source else None,
            "source_set_id": source[3].id if source else None,
            "source_item_ordinal": source[2].ordinal + 1 if source else None,
            "source_is_ai": bool(source[4].is_ai_derived) if source else None,
            "source_occurred_at": source[0].occurred_at.isoformat() if source else None,
            "created_at": ri.created_at.isoformat(), "updated_at": ri.updated_at.isoformat(),
        })
    items.sort(key=lambda item: (
        item["due_at"] or "9999-12-31T00:00:00+00:00",
        0 if item["weakness_status"] == "confirmed" else 1,
        -(datetime.fromisoformat(item["source_occurred_at"]).timestamp() if item["source_occurred_at"] else 0),
    ))
    return items


def create_review_action(db: Session, workspace_id: str, review_item_id: str, action: str, snooze_days: int | None = None) -> dict | None:
    ri = db.scalar(select(ReviewItem).where(ReviewItem.id == review_item_id, ReviewItem.workspace_id == workspace_id).with_for_update())
    if ri is None:
        return None
    if action == "snooze" and snooze_days not in SNOOZE_DAYS:
        return None
    now = _now()
    snooze_until = None
    if action == "reviewing":
        ri.status = "reviewing"
    elif action == "reviewed":
        ri.status = "awaiting_validation"
        ri.due_at = now + timedelta(days=REVIEW_VALIDATION_DAYS)
    elif action == "snooze":
        ri.status = "snoozed"
        snooze_until = now + timedelta(days=snooze_days or 1)
        ri.due_at = snooze_until
    elif action == "dismiss":
        ri.status = "dismissed"
        weakness = db.get(Weakness, ri.weakness_id)
        if weakness is not None:
            weakness.status = "dismissed"
            weakness.revision += 1
    else:
        return None
    ri.last_action_at = now
    db.add(ReviewAction(review_item_id=ri.id, workspace_id=workspace_id, action=action, snooze_until=snooze_until))
    db.commit()
    return {"id": ri.id, "status": ri.status, "due_at": ri.due_at.isoformat() if ri.due_at else None}


# --------------------------------------------------------------------------- #
# Memory CRUD
# --------------------------------------------------------------------------- #

def list_memories(db: Session, workspace_id: str, *, status: str | None = None) -> list[dict]:
    from learn_platform_api.services.learning_projection import refresh_memory_eligibility
    refresh_memory_eligibility(db, workspace_id)
    db.commit()
    statement = (select(LearningMemory, LearningTarget)
                 .join(LearningTarget, LearningMemory.learning_target_id == LearningTarget.id)
                 .where(LearningMemory.workspace_id == workspace_id))
    if status:
        statement = statement.where(LearningMemory.status == status)
    statement = statement.order_by(LearningMemory.updated_at.desc())
    items = []
    for mem, target in db.execute(statement).all():
        source_count = int(db.scalar(select(func.count()).select_from(LearningMemorySource).where(LearningMemorySource.learning_memory_id == mem.id)) or 0)
        user_edited = bool(db.scalar(select(func.count()).select_from(LearningMemoryRevision).where(
            LearningMemoryRevision.learning_memory_id == mem.id,
            LearningMemoryRevision.action == "edit",
        )) or 0)
        source_rows = db.execute(
            select(LearningEvent, PracticeItem, PracticeSet, MasterySignal)
            .join(LearningMemorySource, LearningMemorySource.learning_event_id == LearningEvent.id)
            .join(PracticeAttempt, LearningEvent.practice_attempt_id == PracticeAttempt.id)
            .join(PracticeItem, PracticeAttempt.practice_item_id == PracticeItem.id)
            .join(PracticeSet, PracticeItem.practice_set_id == PracticeSet.id)
            .outerjoin(MasterySignal, (MasterySignal.learning_event_id == LearningEvent.id) & (MasterySignal.learning_target_id == target.id))
            .where(LearningMemorySource.learning_memory_id == mem.id)
            .order_by(LearningEvent.occurred_at.desc()).limit(10)
        ).all()
        lesson = db.get(Lesson, target.lesson_id)
        sources = [{"attempt_id": event.practice_attempt_id, "set_id": practice_set.id,
                    "item_number": item.ordinal + 1, "is_ai": bool(signal.is_ai_derived) if signal else False,
                    "occurred_at": event.occurred_at.isoformat()}
                   for event, item, practice_set, signal in source_rows]
        items.append({
            "id": mem.id, "target_title": _target_title(db, target), "target_key": target.target_key,
            "kind": mem.kind, "status": mem.status,
            "display_text": (f"我需要继续巩固：{_target_title(db, target)}" if mem.kind == "weakness" and not user_edited else _clean_text(mem.display_text)),
            "confirmed_at": mem.confirmed_at.isoformat() if mem.confirmed_at else None,
            "last_supported_at": mem.last_supported_at.isoformat() if mem.last_supported_at else None,
            "source_count": source_count, "course_id": mem.course_id, "lesson_id": mem.lesson_id,
            "lesson_title": _clean_text(lesson.title) if lesson else "", "sources": sources,
        })
    return items


def patch_memory(db: Session, workspace_id: str, memory_id: str, display_text: str | None, action: str | None) -> dict | None:
    mem = db.scalar(select(LearningMemory).where(LearningMemory.id == memory_id, LearningMemory.workspace_id == workspace_id).with_for_update())
    if mem is None:
        return None
    before_hash = _hash(mem.display_text)
    new_revision = mem.revision + 1
    if action == "edit" and display_text is not None:
        mem.display_text = display_text[:2000]
    elif action == "pause":
        mem.status = "paused"
    elif action == "reconfirm":
        mem.status = "active"
        mem.confirmed_at = _now()
    elif action == "archive":
        mem.status = "archived"
    elif display_text is not None:
        mem.display_text = display_text[:2000]
    else:
        return None
    mem.revision = new_revision
    after_hash = _hash(mem.display_text)
    db.add(LearningMemoryRevision(learning_memory_id=mem.id, workspace_id=workspace_id, revision=new_revision, action=action or "edited", before_hash=before_hash, after_hash=after_hash))
    db.commit()
    target = db.get(LearningTarget, mem.learning_target_id)
    return {"id": mem.id, "target_title": target.title if target else "", "status": mem.status, "display_text": mem.display_text, "revision": mem.revision}


def delete_memory(db: Session, workspace_id: str, memory_id: str) -> bool:
    mem = db.scalar(select(LearningMemory).where(LearningMemory.id == memory_id, LearningMemory.workspace_id == workspace_id).with_for_update())
    if mem is None:
        return False
    from learn_platform_api.services.learning_projection import MEMORY_EXPIRY_DAYS
    # Set suppression watermark on weakness.
    if mem.weakness_id:
        weakness = db.get(Weakness, mem.weakness_id)
        if weakness:
            weakness.memory_suppressed_at = _now()
    # Hard delete memory + sources + revisions.
    from sqlalchemy import delete
    db.execute(delete(LearningMemorySource).where(LearningMemorySource.learning_memory_id == memory_id))
    db.execute(delete(LearningMemoryRevision).where(LearningMemoryRevision.learning_memory_id == memory_id))
    db.execute(delete(LearningMemory).where(LearningMemory.id == memory_id))
    db.commit()
    return True


# --------------------------------------------------------------------------- #
# Memory policy
# --------------------------------------------------------------------------- #

def get_memory_policy(db: Session, workspace_id: str) -> dict:
    policy = db.scalar(select(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == workspace_id))
    if policy is None:
        policy = LearningMemoryPolicy(workspace_id=workspace_id, tutor_use_enabled=0, policy_revision=1)
        db.add(policy); db.commit(); db.refresh(policy)
    return {"tutor_use_enabled": bool(policy.tutor_use_enabled), "policy_revision": policy.policy_revision, "updated_at": policy.updated_at.isoformat()}


def patch_memory_policy(db: Session, workspace_id: str, tutor_use_enabled: bool) -> dict:
    policy = db.scalar(select(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == workspace_id).with_for_update())
    if policy is None:
        policy = LearningMemoryPolicy(workspace_id=workspace_id, tutor_use_enabled=0, policy_revision=1)
        db.add(policy); db.flush()
    policy.tutor_use_enabled = 1 if tutor_use_enabled else 0
    policy.policy_revision += 1
    policy.updated_at = _now()
    db.commit()
    return {"tutor_use_enabled": bool(policy.tutor_use_enabled), "policy_revision": policy.policy_revision, "updated_at": policy.updated_at.isoformat()}


# --------------------------------------------------------------------------- #
# Recompute job
# --------------------------------------------------------------------------- #

def create_recompute_job(db: Session, settings: Settings, workspace_id: str, idempotency_key: str) -> LearningProjectionJob:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.lifecycle_status != "active":
        raise LookupError("workspace_not_found")
    request_hash = _hash(f"recompute|{workspace_id}")
    existing = db.scalar(select(LearningProjectionJob).where(LearningProjectionJob.workspace_id == workspace_id, LearningProjectionJob.idempotency_key == idempotency_key))
    if existing:
        if existing.request_hash != request_hash:
            raise ValueError("idempotency_key_conflict")
        return existing
    policy = db.scalar(select(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == workspace_id))
    policy_revision = policy.policy_revision if policy is not None else 0
    job = LearningProjectionJob(
        workspace_id=workspace_id,
        status="queued",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        policy_revision=policy_revision,
        attempt_count=0,
    )
    db.add(job); db.commit(); db.refresh(job)
    from learn_platform_api.services.queue import enqueue_learning_recompute
    try:
        enqueue_learning_recompute(settings, job.id)
    except Exception:
        job.status = "queue_failed"; job.error_code = "queue_unavailable"; job.error_message = "重算队列暂时不可用"; db.commit()
    return job


def get_learning_job(db: Session, workspace_id: str, job_id: str) -> LearningProjectionJob | None:
    return db.scalar(select(LearningProjectionJob).where(LearningProjectionJob.id == job_id, LearningProjectionJob.workspace_id == workspace_id))


def cancel_learning_job(db: Session, workspace_id: str, job_id: str) -> LearningProjectionJob | None:
    job = get_learning_job(db, workspace_id, job_id)
    if job is None:
        return None
    if job.status in {"queued", "retry_wait", "queue_failed"}:
        job.status = "canceled"
        job.completed_at = _now()
        job.next_attempt_at = None
    elif job.status == "running":
        job.status = "cancel_requested"
        job.next_attempt_at = None
    db.commit()
    db.refresh(job)
    return job


def retry_learning_job(db: Session, settings: Settings, workspace_id: str, job_id: str) -> LearningProjectionJob | None:
    job = get_learning_job(db, workspace_id, job_id)
    if job is None:
        return None
    if job.status not in {"failed", "queue_failed", "canceled"}:
        raise ValueError("job_not_retryable")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.lifecycle_status != "active":
        raise LookupError("workspace_not_found")
    policy = db.scalar(select(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == workspace_id))
    job.policy_revision = policy.policy_revision if policy is not None else 0
    job.status = "queued"
    job.worker_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    db.commit()
    from learn_platform_api.services.queue import enqueue_learning_recompute
    try:
        enqueue_learning_recompute(settings, job.id)
    except Exception:
        job.status = "queue_failed"
        job.error_code = "queue_unavailable"
        job.error_message = "Learning recompute queue is temporarily unavailable."
        db.commit()
    db.refresh(job)
    return job

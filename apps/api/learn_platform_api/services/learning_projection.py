"""Deterministic learning projection: signals → mastery → weakness → review → memory.

All logic here is deterministic, idempotent and provider-free. It runs inside the
feedback commit transaction and during full-workspace recompute. No LLM, no
vector search, no time decay — only explicit Beta(1,1) posterior from the last
10 valid signals per target.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    LearningEvent, LearningMemory, LearningMemoryPolicy, LearningMemoryRevision, LearningMemorySource,
    LearningProjectionJob, LearningTarget, MasterySignal, MasteryState, PracticeAttempt, PracticeFeedback,
    PracticeItem, PracticeItemTarget, PracticeSet, ReviewAction, ReviewItem, Weakness, Lesson,
)

MAX_SIGNALS = 10
BAND_INSUFFICIENT = "insufficient"
BAND_NEEDS_REVIEW = "needs_review"
BAND_DEVELOPING = "developing"
BAND_SECURE = "secure"
POLICY_VERSION = "001"

# Band thresholds (ADR 003 §Projection Algorithm).
SCORE_NEEDS_REVIEW = 0.55
SCORE_SECURE = 0.80
MIN_DISTINCT_ATTEMPTS = 2
MIN_TOTAL_WEIGHT = 1.5
SECURE_MIN_ATTEMPTS = 3
SECURE_MIN_SETS = 2

# Signal generation (ADR 003 §Signal Generation).
WEIGHT_DETERMINISTIC = 1.0
WEIGHT_AI = 0.6
VALUE_FULL = 1.0
VALUE_PARTIAL = 0.5
VALUE_NONE = 0.0
NEGATIVE_THRESHOLD = 0.5
POSITIVE_THRESHOLD = 0.8

# Weakness confirmation (ADR 003 §Weakness).
CONFIRM_MIN_ITEMS = 2
RESOLVE_MIN_ITEMS = 2
REVIEW_VALIDATION_DAYS = 3
MEMORY_EXPIRY_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(dt: datetime | None) -> datetime:
    """Normalize a datetime to UTC-aware for comparison (SQLite returns naive)."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _check_memory_expiry(db: Session, target_id: str, workspace_id: str) -> None:
    """§8: Mark active Memory as needs_review if no supporting evidence in 90 days."""
    mem = db.scalar(select(LearningMemory).where(
        LearningMemory.learning_target_id == target_id,
        LearningMemory.workspace_id == workspace_id,
        LearningMemory.status == "active",
    ))
    if mem is None or mem.last_supported_at is None:
        return
    last = _normalize_dt(mem.last_supported_at)
    if (_now() - last).days >= MEMORY_EXPIRY_DAYS:
        mem.status = "needs_review"
        mem.revision += 1
        db.add(LearningMemoryRevision(
            learning_memory_id=mem.id, workspace_id=workspace_id, revision=mem.revision,
            action="conflicted", before_hash=None, after_hash=None,
        ))


def refresh_memory_eligibility(db: Session, workspace_id: str) -> int:
    """Apply time/source eligibility before memories are displayed or used."""
    changed = 0
    rows = list(db.execute(
        select(LearningMemory, LearningTarget)
        .join(LearningTarget, LearningMemory.learning_target_id == LearningTarget.id)
        .where(LearningMemory.workspace_id == workspace_id, LearningMemory.status == "active")
    ).all())
    from learn_platform_api.services.learning import _target_source_degraded
    for memory, target in rows:
        expired = memory.last_supported_at is not None and (
            _now() - _normalize_dt(memory.last_supported_at)
        ).days >= MEMORY_EXPIRY_DAYS
        lesson = db.get(Lesson, target.lesson_id)
        version_superseded = lesson is None or lesson.current_published_version_id != target.lesson_version_id
        if expired or version_superseded or _target_source_degraded(db, target):
            memory.status = "needs_review"
            memory.revision += 1
            db.add(LearningMemoryRevision(
                learning_memory_id=memory.id,
                workspace_id=workspace_id,
                revision=memory.revision,
                action="conflicted",
                before_hash=None,
                after_hash=None,
            ))
            changed += 1
    return changed


def _value_outcome(value: float) -> str:
    if value >= POSITIVE_THRESHOLD:
        return "positive"
    if value < NEGATIVE_THRESHOLD:
        return "negative"
    return "partial"


def _generate_signals_for_attempt(
    db: Session, workspace_id: str, event: LearningEvent, attempt: PracticeAttempt, feedback: PracticeFeedback, item: PracticeItem
) -> list[MasterySignal]:
    """Create one aggregated signal per target from this attempt's feedback.

    Single-choice: value from correct/incorrect, weight 1.0, not AI.
    Short-answer: rubric-weighted criterion average × 0.6 AI weight per target.
    Ungradable, failed, canceled and no-feedback attempts produce no signal.
    """
    if feedback.verdict == "ungradable":
        return []
    item_targets = list(db.scalars(
        select(PracticeItemTarget).where(PracticeItemTarget.practice_item_id == item.id, PracticeItemTarget.workspace_id == workspace_id)
    ))
    if not item_targets:
        return []

    practice_set = db.get(PracticeSet, item.practice_set_id)
    set_id = practice_set.id if practice_set else ""

    # Group targets: criterion-keyed targets (short_answer) vs plain (single_choice).
    by_target: dict[str, list[tuple[str | None, PracticeItemTarget]]] = {}
    for pit in item_targets:
        by_target.setdefault(pit.learning_target_id, []).append((pit.criterion_key, pit))

    signals: list[MasterySignal] = []
    for target_id, entries in by_target.items():
        criterion_keys = {ck for ck, _ in entries if ck is not None}
        if item.item_type == "single_choice":
            value = VALUE_FULL if feedback.verdict == "correct" else VALUE_NONE
            weight = WEIGHT_DETERMINISTIC
            is_ai = 0
        elif item.item_type == "short_answer":
            # §6: Short-answer ALWAYS aggregates from criterion_results by rubric
            # weight, then applies 0.6 AI weight — even when mapped to lesson_overall
            # with criterion_key=None (meaning all criteria map to this target).
            answer_spec = item.answer_spec or {}
            rubric_criteria = answer_spec.get("rubric", [])
            results_map = {r.get("criterion_key"): r for r in (feedback.criterion_results or [])}
            # If criterion_keys is empty (lesson_overall fallback), use ALL criteria.
            relevant_keys = criterion_keys if criterion_keys else {c.get("criterion_key") for c in rubric_criteria}
            weighted_sum = 0.0
            total_weight = 0
            for c in rubric_criteria:
                ck = c.get("criterion_key")
                if ck not in relevant_keys:
                    continue
                rw = c.get("weight", 0)
                met = (results_map.get(ck) or {}).get("met", "none")
                cv = {"full": VALUE_FULL, "partial": VALUE_PARTIAL, "none": VALUE_NONE}.get(met, VALUE_NONE)
                weighted_sum += cv * rw
                total_weight += rw
            value = weighted_sum / total_weight if total_weight > 0 else VALUE_NONE
            weight = WEIGHT_AI
            is_ai = 1
        else:
            value = VALUE_FULL if feedback.verdict == "correct" else VALUE_NONE
            weight = WEIGHT_DETERMINISTIC
            is_ai = 0

        outcome = _value_outcome(value)
        signals.append(MasterySignal(
            learning_event_id=event.id, learning_target_id=target_id, workspace_id=workspace_id,
            practice_item_id=item.id, practice_set_id=set_id, outcome=outcome, value=value, weight=weight,
            source_kind=item.item_type, is_ai_derived=is_ai,
        ))
    return signals


def _recompute_target(db: Session, target_id: str, workspace_id: str, *, suppression_at: datetime | None = None) -> None:
    """Recompute mastery state, weakness, review item and memory for one target.

    If ``suppression_at`` is provided (from a full recompute that preserved a
    prior user-initiated memory deletion), the new weakness inherits it so
    old events do not revive the memory during replay.
    """
    signals = list(db.scalars(
        select(MasterySignal).where(MasterySignal.learning_target_id == target_id, MasterySignal.workspace_id == workspace_id).order_by(MasterySignal.created_at.desc()).limit(MAX_SIGNALS)
    ))
    target = db.get(LearningTarget, target_id)
    if target is None:
        return

    # Beta(1,1) posterior: (1 + Σ vw) / (2 + Σ w).
    if signals:
        num = 1.0 + sum(s.value * s.weight for s in signals)
        den = 2.0 + sum(s.weight for s in signals)
        score = num / den
    else:
        score = 0.5

    # §12: distinct Attempt counts distinct learning events (= distinct attempts),
    # NOT distinct practice_item_id (which collapses repeated attempts on same item).
    distinct_attempts = len({s.learning_event_id for s in signals})
    distinct_sets = len({s.practice_set_id for s in signals})
    total_weight = sum(s.weight for s in signals)
    last_ev = max((s.created_at for s in signals), default=None, key=lambda dt: dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt) if signals else None

    # Determine band.
    if distinct_attempts < MIN_DISTINCT_ATTEMPTS or total_weight < MIN_TOTAL_WEIGHT:
        band = BAND_INSUFFICIENT
    elif score < SCORE_NEEDS_REVIEW:
        band = BAND_NEEDS_REVIEW
    elif score >= SCORE_SECURE and distinct_attempts >= SECURE_MIN_ATTEMPTS and distinct_sets >= SECURE_MIN_SETS:
        band = BAND_SECURE
    else:
        band = BAND_DEVELOPING

    # Upsert mastery state.
    state = db.scalar(select(MasteryState).where(
        MasteryState.learning_target_id == target_id,
        MasteryState.workspace_id == workspace_id,
    ))
    if state is None:
        state = MasteryState(learning_target_id=target_id, workspace_id=workspace_id, band=band, evidence_count=len(signals), distinct_set_count=distinct_sets, projection_score=score, revision=0, policy_version=POLICY_VERSION)
        db.add(state); db.flush()
    state.band = band
    state.evidence_count = len(signals)
    state.distinct_set_count = distinct_sets
    state.projection_score = score
    state.last_evidence_at = last_ev
    state.policy_version = POLICY_VERSION
    state.revision += 1
    state.updated_at = _now()

    # Weakness state machine.
    negative_signals = [s for s in signals if s.value < NEGATIVE_THRESHOLD]
    distinct_neg_items = len({s.practice_item_id for s in negative_signals})
    weakness = db.scalar(select(Weakness).where(
        Weakness.learning_target_id == target_id,
        Weakness.workspace_id == workspace_id,
    ))

    if negative_signals:
        if weakness is None:
            first_neg = negative_signals[-1]
            last_neg = negative_signals[0]
            weakness = Weakness(
                learning_target_id=target_id, workspace_id=workspace_id, status="provisional",
                reason_code="initial_negative_signal",
                first_negative_event_id=first_neg.learning_event_id,
                last_negative_event_id=last_neg.learning_event_id,
                memory_suppressed_at=suppression_at,
                revision=1,
            )
            db.add(weakness); db.flush()
            ri = ReviewItem(
                weakness_id=weakness.id, workspace_id=workspace_id, status="due", due_at=_now(),
                reopen_count=0, reason_snapshot={"target_title": target.title, "event_type": "practice_result", "occurred_at": negative_signals[0].created_at.isoformat() if negative_signals[0].created_at else None},
            )
            db.add(ri)

        # Update weakness events.
        weakness.last_negative_event_id = negative_signals[0].learning_event_id
        if weakness.first_negative_event_id is None:
            weakness.first_negative_event_id = negative_signals[-1].learning_event_id

        # §8: Reopen dismissed weakness when new negative evidence arrives.
        if weakness.status == "dismissed":
            ri = db.scalar(select(ReviewItem).where(ReviewItem.weakness_id == weakness.id))
            latest_negative_at = max(
                (_normalize_dt(s.created_at) for s in negative_signals if s.created_at),
                default=_normalize_dt(None),
            )
            dismissed_at = _normalize_dt(ri.last_action_at) if ri else _normalize_dt(weakness.memory_suppressed_at)
            if latest_negative_at > dismissed_at:
                if ri is None:
                    ri = ReviewItem(
                        weakness_id=weakness.id, workspace_id=workspace_id, status="due", due_at=_now(),
                        reopen_count=1, reason_snapshot={"target_title": target.title, "event_type": "practice_result", "occurred_at": negative_signals[0].created_at.isoformat() if negative_signals[0].created_at else None},
                    )
                    db.add(ri)
                    db.flush()
                elif ri.status == "dismissed":
                    ri.status = "due"; ri.reopen_count += 1; ri.due_at = _now()
                weakness.status = "confirmed" if distinct_neg_items >= CONFIRM_MIN_ITEMS else "provisional"
                weakness.revision += 1
                db.add(ReviewAction(review_item_id=ri.id, workspace_id=workspace_id, action="reopen"))

        # Promote to confirmed.
        if weakness.status == "provisional" and distinct_neg_items >= CONFIRM_MIN_ITEMS and band == BAND_NEEDS_REVIEW:
            weakness.status = "confirmed"
            weakness.reason_code = "confirmed_negative_signals"
            weakness.revision += 1
            _auto_create_memory(db, workspace_id, target, weakness)

        # §8: Resolve only counts positive signals from AFTER weakness creation.
        if weakness.status in {"provisional", "confirmed"} and weakness.created_at:
            post_creation_positive = [s for s in signals if s.value >= POSITIVE_THRESHOLD and s.created_at and _normalize_dt(s.created_at) > _normalize_dt(weakness.created_at)]
            distinct_post_pos_items = len({s.practice_item_id for s in post_creation_positive})
            if distinct_post_pos_items >= RESOLVE_MIN_ITEMS and band == BAND_SECURE:
                weakness.status = "resolved"
                weakness.reason_code = "resolved_positive_signals"
                weakness.revision += 1
                ri = db.scalar(select(ReviewItem).where(ReviewItem.weakness_id == weakness.id))
                if ri and ri.status not in {"resolved", "dismissed"}:
                    ri.status = "resolved"
                _mark_memory_needs_review(db, target_id, "resolved")

    elif weakness and weakness.status != "dismissed":
        if weakness.status in {"provisional", "confirmed"}:
            weakness.status = "resolved" if band == BAND_SECURE else "provisional"
            ri = db.scalar(select(ReviewItem).where(ReviewItem.weakness_id == weakness.id))
            if ri:
                ri.status = "resolved"
            _mark_memory_needs_review(db, target_id, "no_negative_evidence")

    # §8: Check 90-day expiry for active Memory.
    _check_memory_expiry(db, target_id, workspace_id)

    # Clean up state/weakness/review if no signals at all.
    if not signals:
        if weakness:
            ri = db.scalar(select(ReviewItem).where(ReviewItem.weakness_id == weakness.id))
            if ri:
                db.execute(delete(ReviewAction).where(ReviewAction.review_item_id == ri.id))
                db.execute(delete(ReviewItem).where(ReviewItem.id == ri.id))
            if weakness.memory_suppressed_at is not None:
                weakness.status = "dismissed"
                weakness.reason_code = "memory_suppressed"
                weakness.first_negative_event_id = None
                weakness.last_negative_event_id = None
            else:
                db.execute(delete(Weakness).where(Weakness.id == weakness.id))


def _auto_create_memory(db: Session, workspace_id: str, target: LearningTarget, weakness: Weakness) -> None:
    """Idempotently create a weakness Memory when weakness first turns confirmed.

    Respects suppression watermark: if the user previously deleted a Memory for
    this target, it can only be recreated by NEW negative evidence, not by old
    event replay or full recompute.
    """
    # Check if an active (non-archived) memory already exists.
    existing = db.scalar(select(LearningMemory).where(
        LearningMemory.learning_target_id == target.id,
        LearningMemory.workspace_id == workspace_id,
        LearningMemory.status != "archived",
    ))
    if existing is not None:
        linked_event_ids = set(db.scalars(select(LearningMemorySource.learning_event_id).where(
            LearningMemorySource.learning_memory_id == existing.id,
        )))
        supporting = list(db.scalars(select(MasterySignal).where(
            MasterySignal.learning_target_id == target.id,
            MasterySignal.workspace_id == workspace_id,
            MasterySignal.value < NEGATIVE_THRESHOLD,
        )))
        for event_id in {signal.learning_event_id for signal in supporting if signal.learning_event_id} - linked_event_ids:
            db.add(LearningMemorySource(
                learning_memory_id=existing.id,
                learning_event_id=event_id,
                workspace_id=workspace_id,
            ))
        supported_at = max((_normalize_dt(signal.created_at) for signal in supporting if signal.created_at), default=None)
        if supported_at is not None and supported_at > _normalize_dt(existing.last_supported_at):
            existing.last_supported_at = supported_at
        return

    # Suppression watermark: user previously deleted, only new evidence can rebuild.
    if weakness.memory_suppressed_at is not None:
        # Check if any signal AFTER the suppression watermark is negative.
        post_suppress = list(db.scalars(
            select(MasterySignal).where(
                MasterySignal.learning_target_id == target.id,
                MasterySignal.workspace_id == workspace_id,
                MasterySignal.value < NEGATIVE_THRESHOLD,
            ).order_by(MasterySignal.created_at.desc())
        ))
        # Only rebuild if there are >= CONFIRM_MIN_ITEMS distinct items AFTER suppression.
        post_items = {
            s.practice_item_id
            for s in post_suppress
            if s.created_at
            and weakness.memory_suppressed_at
            and _normalize_dt(s.created_at)
            > _normalize_dt(weakness.memory_suppressed_at)
        }
        if len(post_items) < CONFIRM_MIN_ITEMS:
            return  # not enough new evidence to clear watermark
        weakness.memory_suppressed_at = None

    display_text = f"我需要继续巩固：{target.title}"
    mem = LearningMemory(
        workspace_id=workspace_id, course_id=target.course_id, lesson_id=target.lesson_id,
        lesson_version_id=target.lesson_version_id, learning_target_id=target.id, weakness_id=weakness.id,
        kind="weakness", status="active", display_text=display_text,
        confirmed_at=_now(), last_supported_at=_now(), revision=1,
    )
    db.add(mem); db.flush()
    db.add(LearningMemoryRevision(
        learning_memory_id=mem.id, workspace_id=workspace_id, revision=1, action="auto_created",
        before_hash=None, after_hash=hashlib.sha256(display_text.encode()).hexdigest(),
    ))
    # §8: Create source links to supporting negative learning events.
    negative_event_ids = {s.learning_event_id for s in db.scalars(
        select(MasterySignal).where(
            MasterySignal.learning_target_id == target.id,
            MasterySignal.workspace_id == workspace_id,
            MasterySignal.value < NEGATIVE_THRESHOLD,
        )
    ) if s.learning_event_id}
    for event_id in negative_event_ids:
        db.add(LearningMemorySource(
            learning_memory_id=mem.id, learning_event_id=event_id, workspace_id=workspace_id,
        ))


def _mark_memory_needs_review(db: Session, target_id: str, reason: str) -> None:
    """Mark active Memory for a target as needs_review."""
    mem = db.scalar(select(LearningMemory).where(
        LearningMemory.learning_target_id == target_id, LearningMemory.status == "active",
    ))
    if mem:
        mem.status = "needs_review"
        mem.revision += 1
        db.add(LearningMemoryRevision(
            learning_memory_id=mem.id, workspace_id=mem.workspace_id, revision=mem.revision,
            action="conflicted", before_hash=None, after_hash=None,
        ))


def project_attempt_feedback(
    db: Session, workspace_id: str, attempt: PracticeAttempt, feedback: PracticeFeedback
) -> None:
    """Create event + signals + recompute affected targets in one transaction.

    Called from the feedback commit path (single-choice and grading worker).
    Idempotent: the learning_events unique constraint on feedback_id prevents
    duplicate events on replay.
    """
    existing_event = db.scalar(select(LearningEvent).where(LearningEvent.practice_feedback_id == feedback.id))
    if existing_event is not None:
        return  # idempotent: event already exists

    item = db.get(PracticeItem, attempt.practice_item_id)
    if item is None:
        return

    event = LearningEvent(
        workspace_id=workspace_id, event_type="practice_result",
        practice_attempt_id=attempt.id, practice_feedback_id=feedback.id, occurred_at=_now(),
    )
    db.add(event); db.flush()

    signals = _generate_signals_for_attempt(db, workspace_id, event, attempt, feedback, item)
    affected_targets: set[str] = set()
    for sig in signals:
        db.add(sig)
        affected_targets.add(sig.learning_target_id)
    db.flush()  # make new signals visible to _recompute_target's SELECT (autoflush may be off)

    for target_id in affected_targets:
        _recompute_target(db, target_id, workspace_id)


def recompute_workspace(db: Session, workspace_id: str) -> int:
    """Full workspace recompute of mastery/weakness/review state.

    Preserves user-managed Memory (display_text, paused/archived status, revision
    history, source links and suppression watermarks). Only recomputes the
    deterministic derived state: MasteryState, Weakness, ReviewItem, ReviewAction.
    Memory auto-transitions (active→needs_review) still fire during replay.
    """
    # Preserve suppression watermarks before deleting weaknesses.
    suppression_map: dict[str, datetime] = {}
    for w in db.scalars(select(Weakness).where(Weakness.workspace_id == workspace_id, Weakness.memory_suppressed_at.is_not(None))):
        suppression_map[w.learning_target_id] = w.memory_suppressed_at

    # Delete ONLY recomputable derived facts — NOT Memory/Revision/Source.
    db.execute(update(LearningMemory).where(
        LearningMemory.workspace_id == workspace_id,
        LearningMemory.weakness_id.is_not(None),
    ).values(weakness_id=None))
    db.execute(delete(ReviewAction).where(ReviewAction.workspace_id == workspace_id))
    db.execute(delete(ReviewItem).where(ReviewItem.workspace_id == workspace_id))
    db.execute(delete(Weakness).where(Weakness.workspace_id == workspace_id))
    db.execute(delete(MasteryState).where(MasteryState.workspace_id == workspace_id))
    db.flush()

    # Replay all targets. _auto_create_memory is idempotent: if a non-archived
    # Memory already exists for the target, it returns without creating a new one.
    # _mark_memory_needs_review still fires for resolved/conflicting targets.
    targets = list(db.scalars(select(LearningTarget).where(LearningTarget.workspace_id == workspace_id)))
    for target in targets:
        _recompute_target(db, target.id, workspace_id, suppression_at=suppression_map.get(target.id))
        weakness = db.scalar(select(Weakness).where(Weakness.learning_target_id == target.id))
        suppression_at = suppression_map.get(target.id)
        if weakness is None and suppression_at is not None:
            weakness = Weakness(
                learning_target_id=target.id, workspace_id=workspace_id, status="dismissed",
                reason_code="memory_suppressed", memory_suppressed_at=suppression_at, revision=1,
            )
            db.add(weakness)
            db.flush()
        if weakness is not None:
            db.execute(update(LearningMemory).where(
                LearningMemory.workspace_id == workspace_id,
                LearningMemory.learning_target_id == target.id,
            ).values(weakness_id=weakness.id))

    return len(targets)


def delete_attempt_learning_facts(db: Session, workspace_id: str, attempt_id: str, feedback_id: str | None) -> set[str]:
    """Remove event/signal for an attempt, return affected target IDs for recompute."""
    event = db.scalar(select(LearningEvent).where(LearningEvent.practice_attempt_id == attempt_id))
    affected: set[str] = set()
    if event:
        memory_ids = list(db.scalars(select(LearningMemorySource.learning_memory_id).where(
            LearningMemorySource.learning_event_id == event.id,
        )))
        signals = list(db.scalars(select(MasterySignal).where(MasterySignal.learning_event_id == event.id)))
        affected = {s.learning_target_id for s in signals}
        db.execute(update(Weakness).where(Weakness.first_negative_event_id == event.id).values(first_negative_event_id=None))
        db.execute(update(Weakness).where(Weakness.last_negative_event_id == event.id).values(last_negative_event_id=None))
        # Remove memory sources referencing this event.
        db.execute(delete(LearningMemorySource).where(LearningMemorySource.learning_event_id == event.id))
        db.flush()
        for memory_id in memory_ids:
            remaining = db.scalar(select(func.count()).select_from(LearningMemorySource).where(
                LearningMemorySource.learning_memory_id == memory_id,
            )) or 0
            if remaining == 0:
                db.execute(delete(LearningMemoryRevision).where(LearningMemoryRevision.learning_memory_id == memory_id))
                db.execute(delete(LearningMemory).where(LearningMemory.id == memory_id))
            else:
                memory = db.get(LearningMemory, memory_id)
                latest = db.scalar(
                    select(func.max(LearningEvent.occurred_at))
                    .join(LearningMemorySource, LearningMemorySource.learning_event_id == LearningEvent.id)
                    .where(LearningMemorySource.learning_memory_id == memory_id)
                )
                if memory is not None:
                    memory.last_supported_at = latest
                    if memory.status == "active":
                        memory.status = "needs_review"
                        memory.revision += 1
                        db.add(LearningMemoryRevision(
                            learning_memory_id=memory.id, workspace_id=workspace_id,
                            revision=memory.revision, action="conflicted",
                            before_hash=None, after_hash=None,
                        ))
        db.execute(delete(MasterySignal).where(MasterySignal.learning_event_id == event.id))
        db.execute(delete(LearningEvent).where(LearningEvent.id == event.id))
    return affected


def delete_set_learning_facts(db: Session, workspace_id: str, item_ids: list[str]) -> set[str]:
    """Remove learning facts for all attempts in a set, return affected targets."""
    affected: set[str] = set()
    for item_id in item_ids:
        attempts = list(db.scalars(select(PracticeAttempt).where(PracticeAttempt.practice_item_id == item_id)))
        for att in attempts:
            affected |= delete_attempt_learning_facts(db, workspace_id, att.id, None)
    return affected


def delete_course_learning_facts(db: Session, workspace_id: str, course_id: str) -> None:
    """Hard-delete all learning facts for a course."""
    target_ids_select = select(LearningTarget.id).where(LearningTarget.workspace_id == workspace_id, LearningTarget.course_id == course_id)
    db.execute(delete(LearningMemoryRevision).where(LearningMemoryRevision.learning_memory_id.in_(
        select(LearningMemory.id).where(LearningMemory.workspace_id == workspace_id, LearningMemory.course_id == course_id)
    )))
    db.execute(delete(LearningMemorySource).where(LearningMemorySource.learning_memory_id.in_(
        select(LearningMemory.id).where(LearningMemory.workspace_id == workspace_id, LearningMemory.course_id == course_id)
    )))
    db.execute(delete(LearningMemory).where(LearningMemory.workspace_id == workspace_id, LearningMemory.course_id == course_id))
    db.execute(delete(ReviewAction).where(ReviewAction.workspace_id == workspace_id, ReviewAction.review_item_id.in_(
        select(ReviewItem.id).where(ReviewItem.weakness_id.in_(
            select(Weakness.id).where(Weakness.learning_target_id.in_(target_ids_select))
        ))
    )))
    db.execute(delete(ReviewItem).where(ReviewItem.weakness_id.in_(
        select(Weakness.id).where(Weakness.learning_target_id.in_(target_ids_select))
    )))
    db.execute(delete(Weakness).where(Weakness.learning_target_id.in_(target_ids_select)))
    db.execute(delete(MasteryState).where(
        MasteryState.workspace_id == workspace_id,
        MasteryState.learning_target_id.in_(target_ids_select),
    ))
    db.execute(delete(MasterySignal).where(MasterySignal.learning_target_id.in_(target_ids_select)))
    db.execute(delete(LearningEvent).where(LearningEvent.workspace_id == workspace_id, LearningEvent.practice_attempt_id.in_(
        select(PracticeAttempt.id).where(PracticeAttempt.practice_item_id.in_(
            select(PracticeItem.id).where(PracticeItem.practice_set_id.in_(
                select(PracticeSet.id).where(PracticeSet.course_id == course_id)
            ))
        ))
    )))
    db.execute(delete(PracticeItemTarget).where(PracticeItemTarget.learning_target_id.in_(target_ids_select)))
    db.execute(delete(LearningTarget).where(LearningTarget.workspace_id == workspace_id, LearningTarget.course_id == course_id))


def hard_delete_workspace_learning(db: Session, workspace_id: str) -> None:
    """Hard-delete ALL learning facts for a workspace (workspace deletion)."""
    db.execute(delete(LearningMemoryRevision).where(LearningMemoryRevision.workspace_id == workspace_id))
    db.execute(delete(LearningMemorySource).where(LearningMemorySource.workspace_id == workspace_id))
    db.execute(delete(LearningMemoryPolicy).where(LearningMemoryPolicy.workspace_id == workspace_id))
    db.execute(delete(LearningMemory).where(LearningMemory.workspace_id == workspace_id))
    db.execute(delete(ReviewAction).where(ReviewAction.workspace_id == workspace_id))
    db.execute(delete(ReviewItem).where(ReviewItem.workspace_id == workspace_id))
    db.execute(delete(LearningProjectionJob).where(LearningProjectionJob.workspace_id == workspace_id))
    db.execute(delete(Weakness).where(Weakness.workspace_id == workspace_id))
    db.execute(delete(MasteryState).where(MasteryState.workspace_id == workspace_id))
    db.execute(delete(MasterySignal).where(MasterySignal.workspace_id == workspace_id))
    db.execute(delete(LearningEvent).where(LearningEvent.workspace_id == workspace_id))
    db.execute(delete(PracticeItemTarget).where(PracticeItemTarget.workspace_id == workspace_id))
    db.execute(delete(LearningTarget).where(LearningTarget.workspace_id == workspace_id))

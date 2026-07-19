import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, update

from learn_platform_api.db.models import AgentRun, AgentToolCall, TutorTurn
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.tutor_generation import execute_tutor_turn
from learn_platform_api.services.tutor import cleanup_session
from learn_platform_api.settings import get_settings

logger = logging.getLogger(__name__)

#: Transient failures eligible for a bounded retry_wait backoff. Configuration /
#: authority failures (teaching_skill_unavailable, source_snapshot_stale,
#: generation_canceled) are terminal for the attempt — they surface a stable
#: error instead of looping.
RETRYABLE_CODES = {"generation_provider_unavailable", "invalid_agent_artifact"}

ERROR_MESSAGES = {
    "source_snapshot_stale": "课程来源已经变化",
    "generation_provider_unavailable": "Tutor 服务暂时不可用",
    "generation_provider_unconfigured": "Tutor 模型尚未配置",
    "invalid_agent_artifact": "Tutor 回答未通过结构或引用校验",
    "teaching_skill_unavailable": "当前教学 Skill 不可用",
    "agent_step_budget_exceeded": "Tutor 步数预算耗尽",
}


def cleanup_tutor_session(session_id: str) -> None:
    with SessionLocal() as db:
        cleanup_session(db, session_id)


def heartbeat_tutor_turn(turn_id: str, worker_id: str, settings) -> bool:
    current = datetime.now(timezone.utc)
    with SessionLocal() as db:
        updated = db.execute(update(TutorTurn).where(TutorTurn.id == turn_id, TutorTurn.status == "running", TutorTurn.worker_id == worker_id).values(lease_expires_at=current + timedelta(seconds=settings.ingestion_lease_seconds))).rowcount
        db.commit(); return bool(updated)


@contextmanager
def maintain_tutor_lease(turn_id: str, worker_id: str, settings):
    stopped = threading.Event(); lost = threading.Event()
    def loop():
        while not stopped.wait(settings.ingestion_heartbeat_seconds):
            try:
                if not heartbeat_tutor_turn(turn_id, worker_id, settings): lost.set(); return
            except Exception: lost.set(); return
    thread = threading.Thread(target=loop, name=f"tutor-heartbeat-{turn_id}", daemon=True); thread.start()
    try: yield lost
    finally: stopped.set(); thread.join(timeout=5)


def _capture_progress(db, turn: TutorTurn) -> dict:
    """Read the in-progress AgentRun's real step_count and reported usage before
    the worker rolls back (corr 3.9). Usage dimensions stay None unless every
    provider call in that dimension reported a value."""
    try:
        db.flush()
    except Exception:
        return {"step_count": 0, "input_tokens": None, "output_tokens": None}
    run = db.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id, AgentRun.workspace_id == turn.workspace_id, AgentRun.status == "running"))
    if run is None:
        return {"step_count": 0, "input_tokens": None, "output_tokens": None}
    return {"step_count": run.step_count or 0, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens}


def _finish_failed_turn(db, turn: TutorTurn, code: str, progress: dict, settings) -> None:
    """Persist a single failed AgentRun carrying the attempt's real progress.

    The automatic delivery-attempt budget is computed from the count of AgentRuns
    already persisted for this turn (one per delivery attempt), NOT from the
    user-visible ``attempt_number`` (which only increments on explicit retry).
    After counting this failure, the turn enters ``retry_wait`` only while the
    total delivery attempts stay strictly below ``ingestion_max_attempts``; once
    the budget is exhausted it becomes terminal ``failed``. An explicit user
    retry creates a NEW TutorTurn with its own fresh budget (corr 002/3.1).
    """
    canceled = turn.status == "cancel_requested" or code == "generation_canceled"
    # Normally the in-flight run disappears with the execution rollback. If an
    # integration accidentally committed it, reuse and finalize that row rather
    # than leaving a misleading permanent ``running`` trace and adding another.
    in_flight = db.scalar(
        select(AgentRun)
        .where(AgentRun.tutor_turn_id == turn.id, AgentRun.status == "running")
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    prior_attempts = db.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.tutor_turn_id == turn.id,
            AgentRun.status.in_({"succeeded", "failed", "canceled"}),
        )
    ) or 0
    delivery_attempts = prior_attempts + 1
    retryable = code in RETRYABLE_CODES and delivery_attempts < settings.ingestion_max_attempts
    failed_run = in_flight or AgentRun(
        tutor_turn_id=turn.id,
        workspace_id=turn.workspace_id,
        role="tutor",
        attempt_number=turn.attempt_number,
    )
    failed_run.status = "canceled" if canceled else "failed"
    failed_run.step_count = progress["step_count"]
    failed_run.input_tokens = progress["input_tokens"]
    failed_run.output_tokens = progress["output_tokens"]
    failed_run.error_code = code
    failed_run.completed_at = datetime.now(timezone.utc)
    db.add(failed_run)
    if canceled:
        turn.status = "canceled"
        turn.next_attempt_at = None
    elif retryable:
        turn.status = "retry_wait"
        turn.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    else:
        turn.status = "failed"
        turn.next_attempt_at = None
    turn.error_code = code
    turn.error_message = "Tutor 已取消" if canceled else ERROR_MESSAGES.get(code, "Tutor 生成失败")
    turn.completed_at = datetime.now(timezone.utc) if (canceled or not retryable) else None
    turn.lease_expires_at = None


def run_tutor_turn(turn_id: str) -> None:
    settings = get_settings(); worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{turn_id}"; now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        # Claim only queued turns, or retry_wait turns whose backoff has elapsed.
        # A duplicate delivery of an already-claimed/finished turn is a no-op.
        claimed = db.execute(update(TutorTurn).where(
            TutorTurn.id == turn_id,
            (TutorTurn.status == "queued") | ((TutorTurn.status == "retry_wait") & TutorTurn.next_attempt_at.is_not(None) & (TutorTurn.next_attempt_at <= now)),
        ).values(status="running", worker_id=worker_id, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds), error_code=None, error_message=None, next_attempt_at=None)).rowcount
        db.commit()
        if not claimed:
            return
        turn = db.get(TutorTurn, turn_id)
        try:
            with maintain_tutor_lease(turn.id, worker_id, settings) as lease_lost:
                execute_tutor_turn(db, settings, turn, worker_id=worker_id, lease_lost=lease_lost)
                if lease_lost.is_set():
                    raise ValueError("generation_canceled")
            db.commit()
        except ValueError as exc:
            progress = _capture_progress(db, turn)
            db.rollback(); turn = db.get(TutorTurn, turn_id)
            if not turn or turn.worker_id != worker_id:
                # Owner replaced or turn removed: do not write a duplicate run.
                return
            if turn.status == "cancel_requested" or str(exc) == "generation_canceled":
                _finish_failed_turn(db, turn, "generation_canceled", progress, settings)
                db.commit(); return
            if turn.status != "running":
                return
            _finish_failed_turn(db, turn, str(exc), progress, settings)
            db.commit()
        except Exception:
            logger.exception("tutor_internal_error turn_id=%s", turn_id)
            progress = _capture_progress(db, turn)
            db.rollback(); turn = db.get(TutorTurn, turn_id)
            if turn and turn.worker_id == worker_id and turn.status in {"running", "cancel_requested"}:
                canceled = turn.status == "cancel_requested"
                _finish_failed_turn(db, turn, "generation_canceled" if canceled else "generation_internal_error", {"step_count": progress["step_count"], "input_tokens": None, "output_tokens": None}, settings)
                db.commit()

import logging
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy import update

from learn_platform_api.db.models import AgentRun, TutorTurn
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.services.tutor_generation import execute_tutor_turn
from learn_platform_api.services.tutor import cleanup_session
from learn_platform_api.settings import get_settings

logger = logging.getLogger(__name__)


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


def run_tutor_turn(turn_id: str) -> None:
    settings = get_settings(); worker_id = f"{socket.gethostname()}:{threading.get_ident()}:{turn_id}"; now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        claimed = db.execute(update(TutorTurn).where(TutorTurn.id == turn_id, TutorTurn.status.in_({"queued", "retry_wait"})).values(status="running", worker_id=worker_id, lease_expires_at=now + timedelta(seconds=settings.ingestion_lease_seconds), error_code=None, error_message=None)).rowcount
        db.commit()
        if not claimed: return
        turn = db.get(TutorTurn, turn_id)
        try:
            with maintain_tutor_lease(turn.id, worker_id, settings) as lease_lost:
                execute_tutor_turn(db, settings, turn)
                if lease_lost.is_set(): raise ValueError("generation_canceled")
            db.commit()
        except ValueError as exc:
            db.rollback(); turn = db.get(TutorTurn, turn_id)
            if not turn or turn.status not in {"running", "cancel_requested"}: return
            code = str(exc); canceled = turn.status == "cancel_requested" or code == "generation_canceled"; turn.status = "canceled" if canceled else "failed"; turn.error_code = code
            turn.error_message = "Tutor 已取消" if canceled else {"source_snapshot_stale": "课程来源已经变化", "generation_provider_unconfigured": "Tutor 模型尚未配置", "generation_provider_unavailable": "Tutor 服务暂时不可用", "invalid_agent_artifact": "Tutor 回答未通过结构或引用校验"}.get(code, "Tutor 生成失败")
            turn.completed_at = datetime.now(timezone.utc); turn.lease_expires_at = None
            db.add(AgentRun(tutor_turn_id=turn.id, workspace_id=turn.workspace_id, role="tutor", attempt_number=turn.attempt_number, status="canceled" if canceled else "failed", error_code=code, completed_at=turn.completed_at)); db.commit()
        except Exception:
            logger.exception("tutor_internal_error turn_id=%s", turn_id); db.rollback(); turn = db.get(TutorTurn, turn_id)
            if turn and turn.status in {"running", "cancel_requested"}:
                canceled = turn.status == "cancel_requested"
                turn.status = "canceled" if canceled else "failed"; turn.error_code = "generation_canceled" if canceled else "generation_internal_error"; turn.error_message = "Tutor 已取消" if canceled else "Tutor 内部错误"; turn.completed_at = datetime.now(timezone.utc); turn.lease_expires_at = None
                db.add(AgentRun(tutor_turn_id=turn.id, workspace_id=turn.workspace_id, role="tutor", attempt_number=turn.attempt_number, status="canceled" if canceled else "failed", error_code=turn.error_code, completed_at=turn.completed_at)); db.commit()

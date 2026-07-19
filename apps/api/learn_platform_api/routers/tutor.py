import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Workspace
from learn_platform_api.db.session import SessionLocal, get_db
from learn_platform_api.schemas.tutor import TutorSessionCreate, TutorSessionRead, TutorSkillCapabilityRead, TutorTurnCreate, TutorTurnRead
from learn_platform_api.services.tutor import cancel_turn, create_session, create_turn, delete_session, delete_turn, get_turn, list_sessions, retry_turn, session_detail, teaching_skill_capability, turn_detail, _session
from learn_platform_api.settings import get_settings


router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["tutor"])


@router.get("/tutor-skill", response_model=TutorSkillCapabilityRead)
def tutor_skill_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    """Minimal read-only capability: the current published teaching skill.

    Lets the Web show ``教学方法：诊断式支架 v1`` before any session exists.
    A missing or deleting workspace returns a stable 404; a misconfigured skill
    returns 503 so the failure is visible and never silently downgrades.
    """
    workspace = db.get(Workspace, workspace_id)
    if not workspace or workspace.lifecycle_status != "active":
        raise HTTPException(404, "Workspace 不存在")
    try:
        capability = teaching_skill_capability()
    except ValueError:
        raise HTTPException(503, "当前教学 Skill 不可用")
    return {"teaching_skill": capability}


@router.get("/courses/{course_id}/tutor-sessions", response_model=list[TutorSessionRead])
def list_sessions_endpoint(workspace_id: str, course_id: str, course_version_id: str, db: Session = Depends(get_db)):
    try:
        return [session_detail(db, item) for item in list_sessions(db, workspace_id, course_id, course_version_id)]
    except LookupError:
        raise HTTPException(404, "Workspace 不存在")


@router.post("/courses/{course_id}/tutor-sessions", response_model=TutorSessionRead, status_code=201)
def create_session_endpoint(workspace_id: str, course_id: str, payload: TutorSessionCreate, db: Session = Depends(get_db)):
    if not payload.external_processing_ack:
        raise HTTPException(422, "创建 Tutor Session 前必须确认外部处理")
    try: return session_detail(db, create_session(db, get_settings(), workspace_id, course_id, payload.course_version_id))
    except LookupError: raise HTTPException(404, "课程版本不存在")
    except ValueError: raise HTTPException(409, "课程版本不再是当前 Reader 版本")


@router.get("/tutor-sessions/{session_id}", response_model=TutorSessionRead)
def get_session_endpoint(workspace_id: str, session_id: str, db: Session = Depends(get_db)):
    item = _session(db, workspace_id, session_id)
    if not item: raise HTTPException(404, "Tutor Session 不存在")
    return session_detail(db, item)


@router.delete("/tutor-sessions/{session_id}", status_code=202)
def delete_session_endpoint(workspace_id: str, session_id: str, db: Session = Depends(get_db)):
    if not delete_session(db, get_settings(), workspace_id, session_id): raise HTTPException(404, "Tutor Session 不存在")


@router.post("/tutor-sessions/{session_id}/turns", response_model=TutorTurnRead, status_code=status.HTTP_202_ACCEPTED)
def create_turn_endpoint(workspace_id: str, session_id: str, payload: TutorTurnCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    if not idempotency_key or len(idempotency_key) > 200: raise HTTPException(422, "Tutor Turn 需要有效的 Idempotency-Key")
    try: return turn_detail(db, create_turn(db, get_settings(), workspace_id, session_id, payload, idempotency_key))
    except LookupError: raise HTTPException(404, "Tutor Session 不存在")
    except ValueError as exc:
        code = str(exc)
        if code == "teaching_skill_unavailable": raise HTTPException(503, "当前教学 Skill 不可用")
        raise HTTPException(409 if code in {"active_turn_exists", "idempotency_key_conflict", "course_version_inactive"} else 422, code)


@router.get("/tutor-turns/{turn_id}", response_model=TutorTurnRead)
def get_turn_endpoint(workspace_id: str, turn_id: str, db: Session = Depends(get_db)):
    turn = get_turn(db, workspace_id, turn_id)
    if not turn: raise HTTPException(404, "Tutor Turn 不存在")
    return turn_detail(db, turn)


@router.delete("/tutor-turns/{turn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_turn_endpoint(workspace_id: str, turn_id: str, db: Session = Depends(get_db)):
    try:
        deleted = delete_turn(db, workspace_id, turn_id)
    except ValueError:
        raise HTTPException(409, "请先等待当前问答完成或取消正在生成的问答")
    if not deleted:
        raise HTTPException(404, "Tutor Turn 不存在")


@router.post("/tutor-turns/{turn_id}/cancel", response_model=TutorTurnRead)
def cancel_turn_endpoint(workspace_id: str, turn_id: str, db: Session = Depends(get_db)):
    turn = cancel_turn(db, workspace_id, turn_id)
    if not turn: raise HTTPException(404, "Tutor Turn 不存在")
    return turn_detail(db, turn)


@router.post("/tutor-turns/{turn_id}/retry", response_model=TutorTurnRead, status_code=202)
def retry_turn_endpoint(workspace_id: str, turn_id: str, db: Session = Depends(get_db)):
    try: turn = retry_turn(db, get_settings(), workspace_id, turn_id)
    except ValueError: raise HTTPException(409, "当前 Tutor Turn 不能重试")
    if not turn: raise HTTPException(404, "Tutor Turn 不存在")
    return turn_detail(db, turn)


@router.get("/tutor-turns/{turn_id}/events")
def turn_events_endpoint(workspace_id: str, turn_id: str):
    def events():
        previous = None
        for index in range(120):
            with SessionLocal() as db:
                turn = get_turn(db, workspace_id, turn_id)
                if not turn:
                    yield "event: turn.failed\ndata: {\"error_code\":\"turn_not_found\"}\n\n"; return
                if turn.status != previous:
                    if turn.status == "succeeded":
                        detail = turn_detail(db, turn)
                        for block in detail["answer_blocks"] or []:
                            safe_block = {"turn_id": turn.id, "block_key": block["block_key"], "type": block["type"], "text": block["text"], "citation_ids": block["citation_ids"], "certainty": block.get("certainty") if block.get("type") == "learning_diagnosis" else None}
                            yield f"event: answer.delta\ndata: {json.dumps(safe_block, ensure_ascii=False)}\n\n"
                        for citation in detail["citations"]:
                            safe_citation = {key: citation[key] for key in ("citation_id", "block_key", "document_name", "heading_path", "start_offset", "end_offset")}
                            yield f"event: citation.available\ndata: {json.dumps(safe_citation, ensure_ascii=False)}\n\n"
                    name = {"queued": "turn.queued", "running": "turn.started", "succeeded": "turn.completed", "failed": "turn.failed", "canceled": "turn.canceled"}.get(turn.status, "turn.progress")
                    payload = {"turn_id": turn.id, "status": turn.status}
                    yield f"event: {name}\ndata: {json.dumps(payload)}\n\n"; previous = turn.status
                if turn.status in {"succeeded", "failed", "canceled"}: return
                if index and index % 15 == 0:
                    yield "event: heartbeat\ndata: {}\n\n"
            time.sleep(1)
        yield "event: heartbeat\ndata: {}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

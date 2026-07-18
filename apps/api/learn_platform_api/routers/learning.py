"""Learning API router: mastery, review, memory and recompute endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.learning import (
    LearningJobRead, LearningMemoryPatch, LearningMemoryPolicyPatch, LearningMemoryPolicyRead,
    LearningMemoryRead, LearningStateRead, ReviewActionCreate, ReviewItemRead, TargetDetailRead,
)
from learn_platform_api.services.learning import (
    cancel_learning_job, create_recompute_job, create_review_action, delete_memory, get_learning_job, get_memory_policy,
    get_target_detail, list_learning_state, list_memories, list_review_items, patch_memory,
    patch_memory_policy, retry_learning_job,
)
from learn_platform_api.db.models import Workspace
from learn_platform_api.settings import get_settings
from learn_platform_api.services.lesson_completions import complete_lesson, list_completions, undo_completion

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["learning"])


@router.get("/lesson-completions")
def lesson_completions_endpoint(workspace_id: str, course_id: str | None = Query(None), db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return list_completions(db, workspace_id, course_id)


@router.put("/lesson-versions/{lesson_version_id}/completion")
def complete_lesson_endpoint(workspace_id: str, lesson_version_id: str, db: Session = Depends(get_db)):
    try:
        return complete_lesson(db, workspace_id, lesson_version_id)
    except LookupError:
        raise HTTPException(404, "当前已发布课节版本不存在")


@router.delete("/lesson-versions/{lesson_version_id}/completion", status_code=204)
def undo_lesson_completion_endpoint(workspace_id: str, lesson_version_id: str, db: Session = Depends(get_db)):
    if not undo_completion(db, workspace_id, lesson_version_id):
        raise HTTPException(404, "课节完成记录不存在")


def _require_workspace(db: Session, workspace_id: str) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or workspace.lifecycle_status != "active":
        raise HTTPException(404, "Workspace does not exist")


def _job_read(job) -> LearningJobRead:
    return LearningJobRead(id=job.id, workspace_id=job.workspace_id, status=job.status, attempt_count=job.attempt_count, error_code=job.error_code, error_message=job.error_message, created_at=job.created_at, updated_at=job.updated_at, completed_at=job.completed_at)


@router.get("/learning-state", response_model=LearningStateRead)
def learning_state_endpoint(workspace_id: str, course_id: str | None = Query(None), lesson_id: str | None = Query(None), db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return list_learning_state(db, workspace_id, course_id=course_id, lesson_id=lesson_id)


@router.get("/learning-targets/{target_id}", response_model=TargetDetailRead)
def target_detail_endpoint(workspace_id: str, target_id: str, db: Session = Depends(get_db)):
    detail = get_target_detail(db, workspace_id, target_id)
    if detail is None:
        raise HTTPException(404, "学习目标不存在")
    return detail


@router.get("/review-items", response_model=list[ReviewItemRead])
def review_items_endpoint(workspace_id: str, status: Literal["due", "reviewing", "awaiting_validation", "snoozed", "dismissed", "resolved"] | None = Query(None), course_id: str | None = Query(None), db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return list_review_items(db, workspace_id, status=status, course_id=course_id)


@router.post("/review-items/{review_item_id}/actions")
def review_action_endpoint(workspace_id: str, review_item_id: str, payload: ReviewActionCreate, db: Session = Depends(get_db)):
    result = create_review_action(db, workspace_id, review_item_id, payload.action, payload.snooze_days)
    if result is None:
        raise HTTPException(404, "复习项不存在或操作无效")
    return result


@router.post("/learning-state/recompute", response_model=LearningJobRead, status_code=202)
def recompute_endpoint(workspace_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200), db: Session = Depends(get_db)):
    try:
        job = create_recompute_job(db, get_settings(), workspace_id, idempotency_key)
    except LookupError:
        raise HTTPException(404, "Workspace 不存在")
    except ValueError:
        raise HTTPException(409, "重算请求冲突")
    return _job_read(job)


@router.get("/learning-jobs/{job_id}", response_model=LearningJobRead)
def learning_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = get_learning_job(db, workspace_id, job_id)
    if job is None:
        raise HTTPException(404, "重算任务不存在")
    return _job_read(job)


@router.post("/learning-jobs/{job_id}/cancel", response_model=LearningJobRead)
def cancel_learning_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    job = cancel_learning_job(db, workspace_id, job_id)
    if job is None:
        raise HTTPException(404, "Learning recompute job does not exist")
    return _job_read(job)


@router.post("/learning-jobs/{job_id}/retry", response_model=LearningJobRead)
def retry_learning_job_endpoint(workspace_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        job = retry_learning_job(db, get_settings(), workspace_id, job_id)
    except LookupError:
        raise HTTPException(404, "Workspace does not exist")
    except ValueError:
        raise HTTPException(409, "Learning recompute job is not retryable")
    if job is None:
        raise HTTPException(404, "Learning recompute job does not exist")
    return _job_read(job)


@router.get("/learning-memories", response_model=list[LearningMemoryRead])
def memories_endpoint(workspace_id: str, status: Literal["active", "needs_review", "paused", "archived"] | None = Query(None), db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return list_memories(db, workspace_id, status=status)


@router.patch("/learning-memories/{memory_id}", response_model=dict)
def patch_memory_endpoint(workspace_id: str, memory_id: str, payload: LearningMemoryPatch, db: Session = Depends(get_db)):
    result = patch_memory(db, workspace_id, memory_id, payload.display_text, payload.action)
    if result is None:
        raise HTTPException(404, "学习记忆不存在")
    return result


@router.delete("/learning-memories/{memory_id}", status_code=204)
def delete_memory_endpoint(workspace_id: str, memory_id: str, db: Session = Depends(get_db)):
    if not delete_memory(db, workspace_id, memory_id):
        raise HTTPException(404, "学习记忆不存在")


@router.get("/learning-memory-policy", response_model=LearningMemoryPolicyRead)
def get_policy_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return get_memory_policy(db, workspace_id)


@router.patch("/learning-memory-policy", response_model=LearningMemoryPolicyRead)
def patch_policy_endpoint(workspace_id: str, payload: LearningMemoryPolicyPatch, db: Session = Depends(get_db)):
    _require_workspace(db, workspace_id)
    return patch_memory_policy(db, workspace_id, payload.tutor_use_enabled)

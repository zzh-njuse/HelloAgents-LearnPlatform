from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.workspace import WorkspaceCreate, WorkspaceDeletionCreate, WorkspaceDeletionImpact, WorkspaceDeletionJobRead, WorkspaceRead
from learn_platform_api.services.workspaces import (
    create_workspace,
    get_workspace,
    list_workspaces,
)
from learn_platform_api.services.workspace_deletion import create_deletion, deletion_impact, get_deletion_job, retry_deletion
from learn_platform_api.settings import get_settings

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead])
def list_workspace_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return list_workspaces(db, skip=skip, limit=limit)


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace_endpoint(
    payload: WorkspaceCreate, db: Session = Depends(get_db)
):
    return create_workspace(db, payload)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace_endpoint(
    workspace_id: str = Path(min_length=36, max_length=36),
    db: Session = Depends(get_db),
):
    workspace = get_workspace(db, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return workspace


@router.get("/{workspace_id}/deletion-impact", response_model=WorkspaceDeletionImpact)
def workspace_deletion_impact_endpoint(workspace_id: str, db: Session = Depends(get_db)):
    impact = deletion_impact(db, workspace_id)
    if impact is None:
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    return impact


@router.post("/{workspace_id}/deletion", response_model=WorkspaceDeletionJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_workspace_deletion_endpoint(
    workspace_id: str,
    payload: WorkspaceDeletionCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail="删除 Workspace 需要有效的 Idempotency-Key")
    try:
        return create_deletion(db, get_settings(), workspace_id, payload.confirmation_name, idempotency_key)
    except LookupError:
        raise HTTPException(status_code=404, detail="Workspace 不存在")
    except ValueError as exc:
        message = "Workspace 名称不匹配" if str(exc) == "confirmation_mismatch" else "Workspace 正在删除"
        raise HTTPException(status_code=422 if str(exc) == "confirmation_mismatch" else 409, detail=message)


@router.get("/deletion-jobs/{job_id}", response_model=WorkspaceDeletionJobRead)
def get_workspace_deletion_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    job = get_deletion_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Workspace 删除任务不存在")
    return job


@router.post("/deletion-jobs/{job_id}/retry", response_model=WorkspaceDeletionJobRead, status_code=status.HTTP_202_ACCEPTED)
def retry_workspace_deletion_endpoint(job_id: str, db: Session = Depends(get_db)):
    try:
        job = retry_deletion(db, get_settings(), job_id)
    except ValueError:
        raise HTTPException(status_code=409, detail="当前 Workspace 删除任务不能重试")
    if job is None:
        raise HTTPException(status_code=404, detail="Workspace 删除任务不存在")
    return job

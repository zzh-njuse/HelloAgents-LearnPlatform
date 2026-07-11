from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from learn_platform_api.db.session import get_db
from learn_platform_api.schemas.workspace import WorkspaceCreate, WorkspaceRead
from learn_platform_api.services.workspaces import (
    create_workspace,
    get_workspace,
    list_workspaces,
)

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

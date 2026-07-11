import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learn_platform_api.db.models import Workspace
from learn_platform_api.schemas.workspace import WorkspaceCreate


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "workspace")[:140]


def list_workspaces(db: Session, skip: int = 0, limit: int = 100) -> list[Workspace]:
    statement = (
        select(Workspace)
        .order_by(Workspace.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.execute(statement).scalars().all())


def get_workspace(db: Session, workspace_id: str) -> Workspace | None:
    return db.get(Workspace, workspace_id)


def create_workspace(db: Session, payload: WorkspaceCreate) -> Workspace:
    base_slug = slugify(payload.slug or payload.name)

    for suffix in range(1, 1001):
        suffix_text = "" if suffix == 1 else f"-{suffix}"
        slug = f"{base_slug[: 140 - len(suffix_text)]}{suffix_text}"
        workspace = Workspace(
            name=payload.name,
            slug=slug,
            description=payload.description,
        )
        db.add(workspace)
        try:
            db.commit()
            db.refresh(workspace)
            return workspace
        except IntegrityError:
            db.rollback()

    raise RuntimeError("无法生成唯一的 workspace slug")

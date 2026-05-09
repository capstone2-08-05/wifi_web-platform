"""
Project 서비스: CRUD + 본인 소유 권한 체크
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.project import Project
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)


# ============================================
# Internal Helpers
# ============================================
def _get_owned_project_or_404(
    db: Session, project_id: str, current_user: User
) -> Project:
    
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.owner_user_id == current_user.id,
        )
        .first()
    )
    if project is None:
        raise AppError(
            ErrorCode.PROJECT_NOT_FOUND,
            "Project not found.",
            status_code=404,
        )
    return project


# ============================================
# Public API
# ============================================
def create_project(
    db: Session,
    payload: ProjectCreateRequest,
    current_user: User,
) -> ProjectResponse:
    project = Project(
        owner_user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


def list_projects(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    status: str | None = None,
) -> PaginatedResponse[ProjectResponse]:
    base_query = db.query(Project).filter(Project.owner_user_id == current_user.id)
    if status is not None:
        base_query = base_query.filter(Project.status == status)

    total = base_query.with_entities(func.count(Project.id)).scalar() or 0

    items = (
        base_query.order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse[ProjectResponse](
        items=[ProjectResponse.model_validate(p) for p in items],
        page=page,
        page_size=page_size,
        total=total,
    )


def get_project(
    db: Session, project_id: str, current_user: User
) -> ProjectResponse:
    project = _get_owned_project_or_404(db, project_id, current_user)
    return ProjectResponse.model_validate(project)


def update_project(
    db: Session,
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user: User,
) -> ProjectResponse:
    project = _get_owned_project_or_404(db, project_id, current_user)

    update_data = payload.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        update_data["name"] = update_data["name"].strip()

    for field, value in update_data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


def delete_project(db: Session, project_id: str, current_user: User) -> None:
    project = _get_owned_project_or_404(db, project_id, current_user)
    db.delete(project)
    db.commit()
"""
Floor 서비스: CRUD + 본인 소유 프로젝트 권한 체크
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.floor import Floor
from app.models.project import Project
from app.models.user import User
from app.schemas.floor import (
    FloorCreateRequest,
    FloorResponse,
    FloorUpdateRequest,
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


def _get_owned_floor_or_404(
    db: Session, floor_id: str, current_user: User
) -> Floor:
    floor = (
        db.query(Floor)
        .join(Project, Floor.project_id == Project.id)
        .filter(
            Floor.id == floor_id,
            Project.owner_user_id == current_user.id,
        )
        .first()
    )
    if floor is None:
        raise AppError(
            ErrorCode.FLOOR_NOT_FOUND,
            "Floor not found.",
            status_code=404,
        )
    return floor


# ============================================
# Public API
# ============================================
def create_floor(
    db: Session,
    project_id: str,
    payload: FloorCreateRequest,
    current_user: User,
) -> FloorResponse:
    _get_owned_project_or_404(db, project_id, current_user)

    floor = Floor(
        project_id=project_id,
        name=payload.floor_name.strip(),
        floor_index=payload.floor_order,
        default_ceiling_height_m=payload.height_m,
    )
    db.add(floor)
    db.commit()
    db.refresh(floor)
    return FloorResponse.model_validate(floor)


def list_floors_by_project(
    db: Session, project_id: str, current_user: User
) -> list[FloorResponse]:
    _get_owned_project_or_404(db, project_id, current_user)

    floors = (
        db.query(Floor)
        .filter(Floor.project_id == project_id)
        .order_by(Floor.floor_index.asc())
        .all()
    )
    return [FloorResponse.model_validate(f) for f in floors]


def get_floor(
    db: Session, floor_id: str, current_user: User
) -> FloorResponse:
    floor = _get_owned_floor_or_404(db, floor_id, current_user)
    return FloorResponse.model_validate(floor)


def update_floor(
    db: Session,
    floor_id: str,
    payload: FloorUpdateRequest,
    current_user: User,
) -> FloorResponse:
    floor = _get_owned_floor_or_404(db, floor_id, current_user)

    update_data = payload.model_dump(exclude_unset=True)

    field_mapping = {
        "floor_name": "name",
        "floor_order": "floor_index",
        "height_m": "default_ceiling_height_m",
    }

    for spec_field, value in update_data.items():
        if value is None:
            continue
        model_field = field_mapping[spec_field]
        if spec_field == "floor_name":
            value = value.strip()
        setattr(floor, model_field, value)

    db.commit()
    db.refresh(floor)
    return FloorResponse.model_validate(floor)


def delete_floor(db: Session, floor_id: str, current_user: User) -> None:
    floor = _get_owned_floor_or_404(db, floor_id, current_user)
    db.delete(floor)
    db.commit()
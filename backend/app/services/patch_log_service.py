"""Patch Log 조회"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.patch_log import PatchLog
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.patch_log import PatchLogResponse


ALLOWED_TARGET_TYPES = {"room", "wall", "opening", "object"}


def _get_owned_scene_version(
    db: Session, version_id: UUID, user: User
) -> SceneVersion:
    stmt = (
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(version_id),
            Project.owner_user_id == user.id,
        )
    )
    sv = db.execute(stmt).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            status_code=404,
        )
    return sv


def list_patch_logs(
    db: Session,
    version_id: UUID,
    user: User,
    page: int,
    page_size: int,
    target_type: Optional[str] = None,
) -> PaginatedResponse[PatchLogResponse]:
    sv = _get_owned_scene_version(db, version_id, user)

    if target_type is not None and target_type not in ALLOWED_TARGET_TYPES:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            f"Invalid target_type: {target_type}. Allowed: {sorted(ALLOWED_TARGET_TYPES)}",
            status_code=400,
        )

    base = select(PatchLog).where(PatchLog.scene_version_id == sv.id)
    if target_type is not None:
        base = base.where(PatchLog.target_type == target_type)

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = (
        db.execute(
            base.order_by(PatchLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    return PaginatedResponse[PatchLogResponse](
        items=[PatchLogResponse.model_validate(r, from_attributes=True) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )

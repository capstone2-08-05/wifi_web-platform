"""확정본 Opening 단건 조회/수정/삭제 (+ patch_log 자동 기록)"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb
from app.models.opening import Opening
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.models.wall import Wall
from app.schemas.opening import OpeningResponse, OpeningUpdate
from app.services._patch_log_helpers import record_patch, snapshot_opening
from app.services.scene_version_service import _opening_to_response


def _get_owned_opening(db: Session, opening_id: UUID, user: User) -> Opening:
    stmt = (
        select(Opening)
        .join(SceneVersion, Opening.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            Opening.id == str(opening_id),
            Project.owner_user_id == user.id,
        )
    )
    o = db.execute(stmt).scalar_one_or_none()
    if o is None:
        raise AppError(
            ErrorCode.OPENING_NOT_FOUND,
            "Opening not found.",
            status_code=404,
        )
    return o


def _validate_wall_belongs_to_version(
    db: Session, wall_id: UUID, scene_version_id: str
) -> None:
    stmt = select(Wall).where(
        Wall.id == str(wall_id),
        Wall.scene_version_id == scene_version_id,
    )
    if db.execute(stmt).scalar_one_or_none() is None:
        raise AppError(
            ErrorCode.WALL_NOT_FOUND,
            "Referenced wall does not belong to this scene version.",
            status_code=404,
        )


def get_opening(db: Session, opening_id: UUID, user: User) -> OpeningResponse:
    return _opening_to_response(_get_owned_opening(db, opening_id, user))


def update_opening(
    db: Session,
    opening_id: UUID,
    payload: OpeningUpdate,
    user: User,
) -> OpeningResponse:
    opening = _get_owned_opening(db, opening_id, user)
    before = snapshot_opening(opening)

    data = payload.model_dump(exclude_unset=True)
    if "wall_id" in data:
        new_wall_id = data["wall_id"]
        if new_wall_id is not None:
            _validate_wall_belongs_to_version(
                db, new_wall_id, opening.scene_version_id
            )
            opening.wall_id = str(new_wall_id)
        else:
            opening.wall_id = None
    if "line_geom" in data:
        opening.line_geom = geojson_to_wkb(
            data["line_geom"], "LineString", "line_geom"
        )
    if "polygon_geom" in data:
        opening.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    for field in (
        "opening_type",
        "width_m",
        "height_m",
        "sill_height_m",
        "confidence",
        "source_method",
        "metadata_json",
    ):
        if field in data:
            setattr(opening, field, data[field])

    after = snapshot_opening(opening)
    record_patch(
        db,
        scene_version_id=opening.scene_version_id,
        user=user,
        patch_type="update",
        target_type="opening",
        target_id=opening.id,
        before=before,
        after=after,
    )

    try:
        db.commit()
        db.refresh(opening)
    except Exception:
        db.rollback()
        raise
    return _opening_to_response(opening)


def delete_opening(db: Session, opening_id: UUID, user: User) -> None:
    opening = _get_owned_opening(db, opening_id, user)
    before = snapshot_opening(opening)
    sv_id = opening.scene_version_id
    oid = opening.id

    record_patch(
        db,
        scene_version_id=sv_id,
        user=user,
        patch_type="delete",
        target_type="opening",
        target_id=oid,
        before=before,
        after=None,
    )
    db.delete(opening)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

"""확정본 Wall 단건 조회/수정/삭제 (+ patch_log 자동 기록)"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.models.wall import Wall
from app.schemas.scene.wall import WallCreate, WallResponse, WallUpdate
from app.services._patch_log_helpers import record_patch, snapshot_wall
from app.services.scene.scene_version_service import (
    _get_owned_scene_version,
    _wall_to_response,
)


def _get_owned_wall(db: Session, wall_id: UUID, user: User) -> Wall:
    stmt = (
        select(Wall)
        .join(SceneVersion, Wall.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            Wall.id == str(wall_id),
            Project.owner_user_id == user.id,
        )
    )
    w = db.execute(stmt).scalar_one_or_none()
    if w is None:
        raise AppError(
            ErrorCode.WALL_NOT_FOUND,
            "Wall not found.",
            status_code=404,
        )
    return w


def get_wall(db: Session, wall_id: UUID, user: User) -> WallResponse:
    return _wall_to_response(_get_owned_wall(db, wall_id, user))


def create_wall(
    db: Session,
    scene_version_id: UUID,
    payload: WallCreate,
    user: User,
) -> WallResponse:
    """확정본 SceneVersion 에 새 Wall INSERT + patch_log 기록."""
    sv = _get_owned_scene_version(db, scene_version_id, user)

    data = payload.model_dump(exclude_unset=True)
    wall = Wall(scene_version_id=sv.id)
    if "centerline_geom" in data:
        wall.centerline_geom = geojson_to_wkb(
            data["centerline_geom"], "LineString", "centerline_geom"
        )
    if "polygon_geom" in data:
        wall.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    for field in (
        "wall_role",
        "thickness_m",
        "height_m",
        "material_label",
        "confidence",
        "source_method",
        "metadata_json",
    ):
        if field in data:
            setattr(wall, field, data[field])

    db.add(wall)
    db.flush()  # id / created_at 채우기

    after = snapshot_wall(wall)
    record_patch(
        db,
        scene_version_id=wall.scene_version_id,
        user=user,
        patch_type="create",
        target_type="wall",
        target_id=wall.id,
        before=None,
        after=after,
    )

    try:
        db.commit()
        db.refresh(wall)
    except Exception:
        db.rollback()
        raise
    return _wall_to_response(wall)


def update_wall(
    db: Session,
    wall_id: UUID,
    payload: WallUpdate,
    user: User,
) -> WallResponse:
    wall = _get_owned_wall(db, wall_id, user)
    before = snapshot_wall(wall)

    data = payload.model_dump(exclude_unset=True)
    if "centerline_geom" in data:
        wall.centerline_geom = geojson_to_wkb(
            data["centerline_geom"], "LineString", "centerline_geom"
        )
    if "polygon_geom" in data:
        wall.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    for field in (
        "wall_role",
        "thickness_m",
        "height_m",
        "material_label",
        "confidence",
        "source_method",
        "metadata_json",
    ):
        if field in data:
            setattr(wall, field, data[field])

    after = snapshot_wall(wall)
    record_patch(
        db,
        scene_version_id=wall.scene_version_id,
        user=user,
        patch_type="update",
        target_type="wall",
        target_id=wall.id,
        before=before,
        after=after,
    )

    try:
        db.commit()
        db.refresh(wall)
    except Exception:
        db.rollback()
        raise
    return _wall_to_response(wall)


def delete_wall(db: Session, wall_id: UUID, user: User) -> None:
    wall = _get_owned_wall(db, wall_id, user)
    before = snapshot_wall(wall)
    sv_id = wall.scene_version_id
    wid = wall.id

    record_patch(
        db,
        scene_version_id=sv_id,
        user=user,
        patch_type="delete",
        target_type="wall",
        target_id=wid,
        before=before,
        after=None,
    )
    db.delete(wall)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

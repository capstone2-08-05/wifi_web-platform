"""확정본 Room 단건 조회/수정/삭제 (+ patch_log 자동 기록)"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb
from app.models.project import Project
from app.models.room import Room
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.scene.room import RoomCreate, RoomResponse, RoomUpdate
from app.services._patch_log_helpers import record_patch, snapshot_room
from app.services.scene.scene_version_service import (
    _get_owned_scene_version,
    _room_to_response,
)


def _get_owned_room(db: Session, room_id: UUID, user: User) -> Room:
    stmt = (
        select(Room)
        .join(SceneVersion, Room.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            Room.id == str(room_id),
            Project.owner_user_id == user.id,
        )
    )
    r = db.execute(stmt).scalar_one_or_none()
    if r is None:
        raise AppError(
            ErrorCode.ROOM_NOT_FOUND,
            "Room not found.",
            status_code=404,
        )
    return r


def get_room(db: Session, room_id: UUID, user: User) -> RoomResponse:
    return _room_to_response(_get_owned_room(db, room_id, user))


def create_room(
    db: Session,
    scene_version_id: UUID,
    payload: RoomCreate,
    user: User,
) -> RoomResponse:
    """확정본 SceneVersion 에 새 Room INSERT + patch_log 기록."""
    sv = _get_owned_scene_version(db, scene_version_id, user)

    data = payload.model_dump(exclude_unset=True)
    room = Room(scene_version_id=sv.id)
    if "polygon_geom" in data:
        room.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    if "centroid_geom" in data:
        room.centroid_geom = geojson_to_wkb(
            data["centroid_geom"], "Point", "centroid_geom"
        )
    for field in (
        "room_name",
        "room_type",
        "confidence",
        "source_method",
        "metadata_json",
    ):
        if field in data:
            setattr(room, field, data[field])

    db.add(room)
    db.flush()

    after = snapshot_room(room)
    record_patch(
        db,
        scene_version_id=room.scene_version_id,
        user=user,
        patch_type="create",
        target_type="room",
        target_id=room.id,
        before=None,
        after=after,
    )

    try:
        db.commit()
        db.refresh(room)
    except Exception:
        db.rollback()
        raise
    return _room_to_response(room)


def update_room(
    db: Session,
    room_id: UUID,
    payload: RoomUpdate,
    user: User,
) -> RoomResponse:
    room = _get_owned_room(db, room_id, user)
    before = snapshot_room(room)

    data = payload.model_dump(exclude_unset=True)
    if "polygon_geom" in data:
        room.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    if "centroid_geom" in data:
        room.centroid_geom = geojson_to_wkb(
            data["centroid_geom"], "Point", "centroid_geom"
        )
    for field in (
        "room_name",
        "room_type",
        "confidence",
        "source_method",
        "metadata_json",
    ):
        if field in data:
            setattr(room, field, data[field])

    after = snapshot_room(room)
    record_patch(
        db,
        scene_version_id=room.scene_version_id,
        user=user,
        patch_type="update",
        target_type="room",
        target_id=room.id,
        before=before,
        after=after,
    )

    try:
        db.commit()
        db.refresh(room)
    except Exception:
        db.rollback()
        raise
    return _room_to_response(room)


def delete_room(db: Session, room_id: UUID, user: User) -> None:
    room = _get_owned_room(db, room_id, user)
    before = snapshot_room(room)
    sv_id = room.scene_version_id
    rid = room.id

    record_patch(
        db,
        scene_version_id=sv_id,
        user=user,
        patch_type="delete",
        target_type="room",
        target_id=rid,
        before=before,
        after=None,
    )
    db.delete(room)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

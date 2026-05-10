"""Draft Room CRUD + 권한 체크"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb, wkb_to_geojson
from app.models.draft_room import DraftRoom
from app.models.project import Project
from app.models.scene_draft import SceneDraft
from app.models.user import User
from app.schemas.draft_room import (
    DraftRoomCreate,
    DraftRoomResponse,
    DraftRoomUpdate,
)


def _get_owned_scene_draft(
    db: Session, scene_draft_id: UUID, user: User
) -> SceneDraft:
    stmt = (
        select(SceneDraft)
        .join(Project, SceneDraft.project_id == Project.id)
        .where(
            SceneDraft.id == str(scene_draft_id),
            Project.owner_user_id == user.id,
        )
    )
    sd = db.execute(stmt).scalar_one_or_none()
    if sd is None:
        raise AppError(
            ErrorCode.SCENE_DRAFT_NOT_FOUND,
            "Scene draft not found.",
            status_code=404,
        )
    return sd


def _get_owned_draft_room(db: Session, room_id: UUID, user: User) -> DraftRoom:
    stmt = (
        select(DraftRoom)
        .join(SceneDraft, DraftRoom.scene_draft_id == SceneDraft.id)
        .join(Project, SceneDraft.project_id == Project.id)
        .where(
            DraftRoom.id == str(room_id),
            Project.owner_user_id == user.id,
        )
    )
    room = db.execute(stmt).scalar_one_or_none()
    if room is None:
        raise AppError(
            ErrorCode.DRAFT_ROOM_NOT_FOUND,
            "Draft room not found.",
            status_code=404,
        )
    return room


def _to_response(room: DraftRoom) -> DraftRoomResponse:
    return DraftRoomResponse(
        id=room.id,
        scene_draft_id=room.scene_draft_id,
        room_name=room.room_name,
        room_type=room.room_type,
        confidence=room.confidence,
        source_method=room.source_method,
        polygon_geom=wkb_to_geojson(room.polygon_geom),
        centroid_geom=wkb_to_geojson(room.centroid_geom),
        metadata_json=room.metadata_json or {},
        created_at=room.created_at,
    )


def create_draft_room(
    db: Session,
    scene_draft_id: UUID,
    payload: DraftRoomCreate,
    user: User,
) -> DraftRoomResponse:
    sd = _get_owned_scene_draft(db, scene_draft_id, user)
    room = DraftRoom(
        scene_draft_id=sd.id,
        room_name=payload.room_name,
        room_type=payload.room_type,
        confidence=payload.confidence,
        source_method=payload.source_method,
        polygon_geom=geojson_to_wkb(payload.polygon_geom, "Polygon", "polygon_geom"),
        centroid_geom=geojson_to_wkb(payload.centroid_geom, "Point", "centroid_geom"),
        metadata_json=payload.metadata_json if payload.metadata_json is not None else {},
    )
    try:
        db.add(room)
        db.commit()
        db.refresh(room)
    except Exception:
        db.rollback()
        raise
    return _to_response(room)


def update_draft_room(
    db: Session,
    room_id: UUID,
    payload: DraftRoomUpdate,
    user: User,
) -> DraftRoomResponse:
    room = _get_owned_draft_room(db, room_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "polygon_geom" in data:
        room.polygon_geom = geojson_to_wkb(
            data["polygon_geom"], "Polygon", "polygon_geom"
        )
    if "centroid_geom" in data:
        room.centroid_geom = geojson_to_wkb(
            data["centroid_geom"], "Point", "centroid_geom"
        )
    for field in ("room_name", "room_type", "confidence", "source_method", "metadata_json"):
        if field in data:
            setattr(room, field, data[field])
    try:
        db.commit()
        db.refresh(room)
    except Exception:
        db.rollback()
        raise
    return _to_response(room)


def delete_draft_room(db: Session, room_id: UUID, user: User) -> None:
    room = _get_owned_draft_room(db, room_id, user)
    try:
        db.delete(room)
        db.commit()
    except Exception:
        db.rollback()
        raise

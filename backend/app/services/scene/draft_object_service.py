"""Draft Object CRUD + 권한 체크"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb, wkb_to_geojson
from app.models.draft_object import DraftObject
from app.models.project import Project
from app.models.scene_draft import SceneDraft
from app.models.user import User
from app.schemas.scene.draft_object import (
    DraftObjectCreate,
    DraftObjectResponse,
    DraftObjectUpdate,
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


def _get_owned_draft_object(
    db: Session, object_id: UUID, user: User
) -> DraftObject:
    stmt = (
        select(DraftObject)
        .join(SceneDraft, DraftObject.scene_draft_id == SceneDraft.id)
        .join(Project, SceneDraft.project_id == Project.id)
        .where(
            DraftObject.id == str(object_id),
            Project.owner_user_id == user.id,
        )
    )
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise AppError(
            ErrorCode.DRAFT_OBJECT_NOT_FOUND,
            "Draft object not found.",
            status_code=404,
        )
    return obj


def _to_response(obj: DraftObject) -> DraftObjectResponse:
    return DraftObjectResponse(
        id=obj.id,
        scene_draft_id=obj.scene_draft_id,
        object_type=obj.object_type,
        confidence=obj.confidence,
        source_method=obj.source_method,
        point_geom=wkb_to_geojson(obj.point_geom),
        z_m=obj.z_m,
        metadata_json=obj.metadata_json or {},
        created_at=obj.created_at,
    )


def create_draft_object(
    db: Session,
    scene_draft_id: UUID,
    payload: DraftObjectCreate,
    user: User,
) -> DraftObjectResponse:
    sd = _get_owned_scene_draft(db, scene_draft_id, user)
    obj = DraftObject(
        scene_draft_id=sd.id,
        object_type=payload.object_type,
        confidence=payload.confidence,
        source_method=payload.source_method,
        point_geom=geojson_to_wkb(payload.point_geom, "Point", "point_geom"),
        z_m=payload.z_m,
        metadata_json=payload.metadata_json if payload.metadata_json is not None else {},
    )
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    except Exception:
        db.rollback()
        raise
    return _to_response(obj)


def update_draft_object(
    db: Session,
    object_id: UUID,
    payload: DraftObjectUpdate,
    user: User,
) -> DraftObjectResponse:
    obj = _get_owned_draft_object(db, object_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "point_geom" in data:
        obj.point_geom = geojson_to_wkb(data["point_geom"], "Point", "point_geom")
    for field in ("object_type", "confidence", "source_method", "z_m", "metadata_json"):
        if field in data:
            setattr(obj, field, data[field])
    try:
        db.commit()
        db.refresh(obj)
    except Exception:
        db.rollback()
        raise
    return _to_response(obj)


def delete_draft_object(db: Session, object_id: UUID, user: User) -> None:
    obj = _get_owned_draft_object(db, object_id, user)
    try:
        db.delete(obj)
        db.commit()
    except Exception:
        db.rollback()
        raise

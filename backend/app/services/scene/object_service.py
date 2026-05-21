"""확정본 Object 단건 조회/수정/삭제 (+ patch_log 자동 기록)"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb
from app.models.object import SceneObject
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.scene_object import ObjectCreate, ObjectResponse, ObjectUpdate
from app.services._patch_log_helpers import record_patch, snapshot_object
from app.services.scene.scene_version_service import (
    _get_owned_scene_version,
    _object_to_response,
)


def _get_owned_object(db: Session, object_id: UUID, user: User) -> SceneObject:
    stmt = (
        select(SceneObject)
        .join(SceneVersion, SceneObject.scene_version_id == SceneVersion.id)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneObject.id == str(object_id),
            Project.owner_user_id == user.id,
        )
    )
    o = db.execute(stmt).scalar_one_or_none()
    if o is None:
        raise AppError(
            ErrorCode.OBJECT_NOT_FOUND,
            "Object not found.",
            status_code=404,
        )
    return o


def get_object(db: Session, object_id: UUID, user: User) -> ObjectResponse:
    return _object_to_response(_get_owned_object(db, object_id, user))


def create_object(
    db: Session,
    scene_version_id: UUID,
    payload: ObjectCreate,
    user: User,
) -> ObjectResponse:
    """확정본 SceneVersion 에 새 Object INSERT + patch_log 기록."""
    sv = _get_owned_scene_version(db, scene_version_id, user)

    data = payload.model_dump(exclude_unset=True)
    obj = SceneObject(
        scene_version_id=sv.id,
        object_type=data["object_type"],
    )
    if "point_geom" in data:
        obj.point_geom = geojson_to_wkb(
            data["point_geom"], "Point", "point_geom"
        )
    for field in (
        "confidence",
        "source_method",
        "z_m",
        "metadata_json",
    ):
        if field in data:
            setattr(obj, field, data[field])

    db.add(obj)
    db.flush()

    after = snapshot_object(obj)
    record_patch(
        db,
        scene_version_id=obj.scene_version_id,
        user=user,
        patch_type="create",
        target_type="object",
        target_id=obj.id,
        before=None,
        after=after,
    )

    try:
        db.commit()
        db.refresh(obj)
    except Exception:
        db.rollback()
        raise
    return _object_to_response(obj)


def update_object(
    db: Session,
    object_id: UUID,
    payload: ObjectUpdate,
    user: User,
) -> ObjectResponse:
    obj = _get_owned_object(db, object_id, user)
    before = snapshot_object(obj)

    data = payload.model_dump(exclude_unset=True)
    if "point_geom" in data:
        obj.point_geom = geojson_to_wkb(
            data["point_geom"], "Point", "point_geom"
        )
    for field in (
        "object_type",
        "confidence",
        "source_method",
        "z_m",
        "metadata_json",
    ):
        if field in data:
            setattr(obj, field, data[field])

    after = snapshot_object(obj)
    record_patch(
        db,
        scene_version_id=obj.scene_version_id,
        user=user,
        patch_type="update",
        target_type="object",
        target_id=obj.id,
        before=before,
        after=after,
    )

    try:
        db.commit()
        db.refresh(obj)
    except Exception:
        db.rollback()
        raise
    return _object_to_response(obj)


def delete_object(db: Session, object_id: UUID, user: User) -> None:
    obj = _get_owned_object(db, object_id, user)
    before = snapshot_object(obj)
    sv_id = obj.scene_version_id
    oid = obj.id

    record_patch(
        db,
        scene_version_id=sv_id,
        user=user,
        patch_type="delete",
        target_type="object",
        target_id=oid,
        before=before,
        after=None,
    )
    db.delete(obj)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

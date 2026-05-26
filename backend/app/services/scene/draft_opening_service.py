"""Draft Opening CRUD + 권한 체크"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb, wkb_to_geojson
from app.models.draft_opening import DraftOpening
from app.models.draft_wall import DraftWall
from app.models.project import Project
from app.models.scene_draft import SceneDraft
from app.models.user import User
from app.schemas.scene.draft_opening import (
    DraftOpeningCreate,
    DraftOpeningResponse,
    DraftOpeningUpdate,
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


def _get_owned_draft_opening(
    db: Session, opening_id: UUID, user: User
) -> DraftOpening:
    stmt = (
        select(DraftOpening)
        .join(SceneDraft, DraftOpening.scene_draft_id == SceneDraft.id)
        .join(Project, SceneDraft.project_id == Project.id)
        .where(
            DraftOpening.id == str(opening_id),
            Project.owner_user_id == user.id,
        )
    )
    opening = db.execute(stmt).scalar_one_or_none()
    if opening is None:
        raise AppError(
            ErrorCode.DRAFT_OPENING_NOT_FOUND,
            "Draft opening not found.",
            status_code=404,
        )
    return opening


def _validate_wall_belongs_to_draft(
    db: Session, wall_id: UUID, scene_draft_id: str
) -> None:
    """wall_id 가 같은 scene_draft 에 속하는지 검증. 다르면 DRAFT_WALL_NOT_FOUND 404."""
    stmt = select(DraftWall).where(
        DraftWall.id == str(wall_id),
        DraftWall.scene_draft_id == scene_draft_id,
    )
    if db.execute(stmt).scalar_one_or_none() is None:
        raise AppError(
            ErrorCode.DRAFT_WALL_NOT_FOUND,
            "Referenced draft wall does not belong to this scene draft.",
            status_code=404,
        )


def _to_response(opening: DraftOpening) -> DraftOpeningResponse:
    return DraftOpeningResponse(
        id=opening.id,
        scene_draft_id=opening.scene_draft_id,
        wall_id=opening.wall_id,
        opening_type=opening.opening_type,
        width_m=opening.width_m,
        height_m=opening.height_m,
        sill_height_m=opening.sill_height_m,
        confidence=opening.confidence,
        source_method=opening.source_method,
        line_geom=wkb_to_geojson(opening.line_geom),
        polygon_geom=wkb_to_geojson(opening.polygon_geom),
        metadata_json=opening.metadata_json or {},
        created_at=opening.created_at,
    )


def create_draft_opening(
    db: Session,
    scene_draft_id: UUID,
    payload: DraftOpeningCreate,
    user: User,
) -> DraftOpeningResponse:
    sd = _get_owned_scene_draft(db, scene_draft_id, user)
    if payload.wall_id is not None:
        _validate_wall_belongs_to_draft(db, payload.wall_id, sd.id)
    opening = DraftOpening(
        scene_draft_id=sd.id,
        wall_id=str(payload.wall_id) if payload.wall_id is not None else None,
        opening_type=payload.opening_type,
        width_m=payload.width_m,
        height_m=payload.height_m,
        sill_height_m=payload.sill_height_m,
        confidence=payload.confidence,
        source_method=payload.source_method,
        line_geom=geojson_to_wkb(payload.line_geom, "LineString", "line_geom"),
        polygon_geom=geojson_to_wkb(payload.polygon_geom, "Polygon", "polygon_geom"),
        metadata_json=payload.metadata_json if payload.metadata_json is not None else {},
    )
    try:
        db.add(opening)
        db.commit()
        db.refresh(opening)
    except Exception:
        db.rollback()
        raise
    return _to_response(opening)


def update_draft_opening(
    db: Session,
    opening_id: UUID,
    payload: DraftOpeningUpdate,
    user: User,
) -> DraftOpeningResponse:
    opening = _get_owned_draft_opening(db, opening_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "wall_id" in data:
        new_wall_id = data["wall_id"]
        if new_wall_id is not None:
            _validate_wall_belongs_to_draft(db, new_wall_id, opening.scene_draft_id)
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
    try:
        db.commit()
        db.refresh(opening)
    except Exception:
        db.rollback()
        raise
    return _to_response(opening)


def delete_draft_opening(db: Session, opening_id: UUID, user: User) -> None:
    opening = _get_owned_draft_opening(db, opening_id, user)
    try:
        db.delete(opening)
        db.commit()
    except Exception:
        db.rollback()
        raise

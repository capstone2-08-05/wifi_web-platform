"""Draft Wall CRUD + 권한 체크"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb, wkb_to_geojson
from app.models.draft_wall import DraftWall
from app.models.project import Project
from app.models.scene_draft import SceneDraft
from app.models.user import User
from app.schemas.draft_wall import (
    DraftWallCreate,
    DraftWallResponse,
    DraftWallUpdate,
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


def _get_owned_draft_wall(db: Session, wall_id: UUID, user: User) -> DraftWall:
    stmt = (
        select(DraftWall)
        .join(SceneDraft, DraftWall.scene_draft_id == SceneDraft.id)
        .join(Project, SceneDraft.project_id == Project.id)
        .where(
            DraftWall.id == str(wall_id),
            Project.owner_user_id == user.id,
        )
    )
    wall = db.execute(stmt).scalar_one_or_none()
    if wall is None:
        raise AppError(
            ErrorCode.DRAFT_WALL_NOT_FOUND,
            "Draft wall not found.",
            status_code=404,
        )
    return wall


def _to_response(wall: DraftWall) -> DraftWallResponse:
    return DraftWallResponse(
        id=wall.id,
        scene_draft_id=wall.scene_draft_id,
        wall_role=wall.wall_role,
        thickness_m=wall.thickness_m,
        height_m=wall.height_m,
        material_label=wall.material_label,
        confidence=wall.confidence,
        source_method=wall.source_method,
        centerline_geom=wkb_to_geojson(wall.centerline_geom),
        polygon_geom=wkb_to_geojson(wall.polygon_geom),
        metadata_json=wall.metadata_json or {},
        created_at=wall.created_at,
    )


def create_draft_wall(
    db: Session,
    scene_draft_id: UUID,
    payload: DraftWallCreate,
    user: User,
) -> DraftWallResponse:
    sd = _get_owned_scene_draft(db, scene_draft_id, user)
    data = payload.model_dump(exclude_unset=True)
    wall = DraftWall(
        scene_draft_id=sd.id,
        centerline_geom=geojson_to_wkb(
            data.get("centerline_geom"), "LineString", "centerline_geom"
        )
        if "centerline_geom" in data
        else None,
        polygon_geom=geojson_to_wkb(
            data.get("polygon_geom"), "Polygon", "polygon_geom"
        )
        if "polygon_geom" in data
        else None,
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
    try:
        db.add(wall)
        db.commit()
        db.refresh(wall)
    except Exception:
        db.rollback()
        raise
    return _to_response(wall)


def update_draft_wall(
    db: Session,
    wall_id: UUID,
    payload: DraftWallUpdate,
    user: User,
) -> DraftWallResponse:
    wall = _get_owned_draft_wall(db, wall_id, user)
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
    try:
        db.commit()
        db.refresh(wall)
    except Exception:
        db.rollback()
        raise
    return _to_response(wall)


def delete_draft_wall(db: Session, wall_id: UUID, user: User) -> None:
    wall = _get_owned_draft_wall(db, wall_id, user)
    try:
        db.delete(wall)
        db.commit()
    except Exception:
        db.rollback()
        raise

"""Scene Version: promote + 조회 + set-current"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
from app.models.floor import Floor
from app.models.object import SceneObject
from app.models.opening import Opening
from app.models.project import Project
from app.models.room import Room
from app.models.scene_draft import SceneDraft
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.models.wall import Wall
from app.schemas.scene.opening import OpeningResponse
from app.schemas.scene.room import RoomResponse
from app.schemas.scene.scene_object import ObjectResponse
from app.schemas.scene.scene_version import (
    PromoteRequest,
    SceneVersionDetailResponse,
    SceneVersionResponse,
)
from app.schemas.scene.wall import WallResponse


# ---------------------------------------------------------------------------
# 권한 체크
# ---------------------------------------------------------------------------
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
        .options(
            selectinload(SceneDraft.draft_rooms),
            selectinload(SceneDraft.draft_walls),
            selectinload(SceneDraft.draft_openings),
            selectinload(SceneDraft.draft_objects),
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


def _get_owned_scene_version(
    db: Session, version_id: UUID, user: User, with_children: bool = False
) -> SceneVersion:
    stmt = (
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(version_id),
            Project.owner_user_id == user.id,
        )
    )
    if with_children:
        stmt = stmt.options(
            selectinload(SceneVersion.rooms),
            selectinload(SceneVersion.walls),
            selectinload(SceneVersion.openings),
            selectinload(SceneVersion.objects),
        )
    sv = db.execute(stmt).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            status_code=404,
        )
    return sv


def _get_owned_floor(db: Session, floor_id: UUID, user: User) -> Floor:
    stmt = (
        select(Floor)
        .join(Project, Floor.project_id == Project.id)
        .where(
            Floor.id == str(floor_id),
            Project.owner_user_id == user.id,
        )
    )
    f = db.execute(stmt).scalar_one_or_none()
    if f is None:
        raise AppError(
            ErrorCode.FLOOR_NOT_FOUND,
            "Floor not found.",
            status_code=404,
        )
    return f


# ---------------------------------------------------------------------------
# 변환 헬퍼
# ---------------------------------------------------------------------------
def _to_summary(sv: SceneVersion) -> SceneVersionResponse:
    return SceneVersionResponse(
        id=sv.id,
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        source_draft_id=sv.scene_draft_id,
        version_no=sv.version_no,
        is_current=sv.is_confirmed,
        source_mode=sv.source_mode,
        source_method=sv.source_method,
        source_asset_id=sv.source_asset_id,
        render_scene_url=sv.render_scene_url,
        rf_scene_url=sv.rf_scene_url,
        artifacts_json=sv.artifacts_json or {},
        created_by=sv.created_by,
        created_at=sv.created_at,
    )


def _room_to_response(r: Room) -> RoomResponse:
    return RoomResponse(
        id=r.id,
        scene_version_id=r.scene_version_id,
        room_name=r.room_name,
        room_type=r.room_type,
        confidence=r.confidence,
        source_method=r.source_method,
        polygon_geom=wkb_to_geojson(r.polygon_geom),
        centroid_geom=wkb_to_geojson(r.centroid_geom),
        metadata_json=r.metadata_json or {},
        created_at=r.created_at,
    )


def _wall_to_response(w: Wall) -> WallResponse:
    return WallResponse(
        id=w.id,
        scene_version_id=w.scene_version_id,
        wall_role=w.wall_role,
        thickness_m=w.thickness_m,
        height_m=w.height_m,
        material_label=w.material_label,
        confidence=w.confidence,
        source_method=w.source_method,
        centerline_geom=wkb_to_geojson(w.centerline_geom),
        polygon_geom=wkb_to_geojson(w.polygon_geom),
        metadata_json=w.metadata_json or {},
        created_at=w.created_at,
    )


def _opening_to_response(o: Opening) -> OpeningResponse:
    return OpeningResponse(
        id=o.id,
        scene_version_id=o.scene_version_id,
        wall_id=o.wall_id,
        opening_type=o.opening_type,
        width_m=o.width_m,
        height_m=o.height_m,
        sill_height_m=o.sill_height_m,
        confidence=o.confidence,
        source_method=o.source_method,
        line_geom=wkb_to_geojson(o.line_geom),
        polygon_geom=wkb_to_geojson(o.polygon_geom),
        metadata_json=o.metadata_json or {},
        created_at=o.created_at,
    )


def _object_to_response(o: SceneObject) -> ObjectResponse:
    return ObjectResponse(
        id=o.id,
        scene_version_id=o.scene_version_id,
        object_type=o.object_type,
        confidence=o.confidence,
        source_method=o.source_method,
        point_geom=wkb_to_geojson(o.point_geom),
        z_m=o.z_m,
        metadata_json=o.metadata_json or {},
        created_at=o.created_at,
    )


# ---------------------------------------------------------------------------
# 퍼블릭 API
# ---------------------------------------------------------------------------
def promote(
    db: Session,
    scene_draft_id: UUID,
    payload: PromoteRequest,
    user: User,
) -> SceneVersionResponse:
    sd = _get_owned_scene_draft(db, scene_draft_id, user)

    existing = db.execute(
        select(SceneVersion).where(SceneVersion.scene_draft_id == sd.id)
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError(
            ErrorCode.DRAFT_ALREADY_PROMOTED,
            f"Scene draft is already promoted to version {existing.version_no}.",
            status_code=409,
        )

    if payload.is_current:
        db.execute(
            update(SceneVersion)
            .where(
                SceneVersion.floor_id == sd.floor_id,
                SceneVersion.is_confirmed.is_(True),
            )
            .values(is_confirmed=False)
        )

    sv = SceneVersion(
        project_id=sd.project_id,
        floor_id=sd.floor_id,
        scene_draft_id=sd.id,
        version_no=payload.version_no,
        is_confirmed=payload.is_current,
        source_mode=sd.source_mode,
        source_asset_id=sd.source_asset_id,
        source_method=sd.source_method,
        artifacts_json={},
        created_by=user.email,
    )
    db.add(sv)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.SCENE_VERSION_CONFLICT,
            f"Version {payload.version_no} already exists for this floor.",
            status_code=409,
        ) from exc

    draft_wall_to_wall: dict[str, str] = {}

    for dr in sd.draft_rooms:
        db.add(
            Room(
                scene_version_id=sv.id,
                room_name=dr.room_name,
                room_type=dr.room_type,
                confidence=dr.confidence,
                source_method=dr.source_method,
                polygon_geom=dr.polygon_geom,
                centroid_geom=dr.centroid_geom,
                metadata_json=dr.metadata_json or {},
            )
        )

    for dw in sd.draft_walls:
        wall = Wall(
            scene_version_id=sv.id,
            wall_role=dw.wall_role,
            thickness_m=dw.thickness_m,
            height_m=dw.height_m,
            material_label=dw.material_label,
            confidence=dw.confidence,
            source_method=dw.source_method,
            centerline_geom=dw.centerline_geom,
            polygon_geom=dw.polygon_geom,
            metadata_json=dw.metadata_json or {},
        )
        db.add(wall)
        db.flush()
        draft_wall_to_wall[dw.id] = wall.id

    for op in sd.draft_openings:
        db.add(
            Opening(
                scene_version_id=sv.id,
                wall_id=draft_wall_to_wall.get(op.wall_id) if op.wall_id else None,
                opening_type=op.opening_type,
                width_m=op.width_m,
                height_m=op.height_m,
                sill_height_m=op.sill_height_m,
                confidence=op.confidence,
                source_method=op.source_method,
                line_geom=op.line_geom,
                polygon_geom=op.polygon_geom,
                metadata_json=op.metadata_json or {},
            )
        )

    for ob in sd.draft_objects:
        db.add(
            SceneObject(
                scene_version_id=sv.id,
                object_type=ob.object_type,
                confidence=ob.confidence,
                source_method=ob.source_method,
                point_geom=ob.point_geom,
                z_m=ob.z_m,
                metadata_json=ob.metadata_json or {},
            )
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(sv)
    return _to_summary(sv)


def get_scene_version(
    db: Session, version_id: UUID, user: User
) -> SceneVersionDetailResponse:
    sv = _get_owned_scene_version(db, version_id, user, with_children=True)
    summary = _to_summary(sv)
    return SceneVersionDetailResponse(
        **summary.model_dump(),
        rooms=[_room_to_response(r) for r in sv.rooms],
        walls=[_wall_to_response(w) for w in sv.walls],
        openings=[_opening_to_response(o) for o in sv.openings],
        objects=[_object_to_response(o) for o in sv.objects],
    )


def list_by_floor(
    db: Session,
    floor_id: UUID,
    user: User,
    is_current: Optional[bool] = None,
) -> list[SceneVersionResponse]:
    _get_owned_floor(db, floor_id, user)
    stmt = select(SceneVersion).where(SceneVersion.floor_id == str(floor_id))
    if is_current is not None:
        stmt = stmt.where(SceneVersion.is_confirmed.is_(is_current))
    stmt = stmt.order_by(SceneVersion.version_no.desc())
    rows = db.execute(stmt).scalars().all()
    return [_to_summary(r) for r in rows]


def set_current(
    db: Session, version_id: UUID, user: User
) -> SceneVersionResponse:
    sv = _get_owned_scene_version(db, version_id, user)
    db.execute(
        update(SceneVersion)
        .where(
            SceneVersion.floor_id == sv.floor_id,
            SceneVersion.id != sv.id,
            SceneVersion.is_confirmed.is_(True),
        )
        .values(is_confirmed=False)
    )
    sv.is_confirmed = True
    try:
        db.commit()
        db.refresh(sv)
    except Exception:
        db.rollback()
        raise
    return _to_summary(sv)


def delete_version(db: Session, version_id: UUID, user: User) -> None:
    """확정본 Scene Version 삭제.

    FK 가 ON DELETE CASCADE 로 걸려있어 children (walls/rooms/openings/objects),
    patch_logs, rf_runs 까지 자동 정리됨.

    현재 활성(is_confirmed) 버전을 삭제하면 같은 floor 의 다른 버전 중 가장 최근
    것을 자동으로 활성화. 마지막 버전이면 활성 버전이 없는 상태로 남음.
    """
    sv = _get_owned_scene_version(db, version_id, user)
    was_active = bool(sv.is_confirmed)
    floor_id = sv.floor_id

    db.delete(sv)
    db.flush()

    if was_active:
        next_sv = db.execute(
            select(SceneVersion)
            .where(SceneVersion.floor_id == floor_id)
            .order_by(SceneVersion.version_no.desc())
            .limit(1)
        ).scalar_one_or_none()
        if next_sv is not None:
            next_sv.is_confirmed = True

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

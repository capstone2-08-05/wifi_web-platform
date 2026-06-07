"""Scene Version 라우터"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene.opening import OpeningCreate, OpeningResponse
from app.schemas.scene.room import RoomCreate, RoomResponse
from app.schemas.scene.scene_object import ObjectCreate, ObjectResponse
from app.schemas.scene.scene_draft import SceneDraftRescaleRequest
from app.schemas.scene.scene_version import (
    PromoteRequest,
    SceneVersionDetailResponse,
    SceneVersionResponse,
)
from app.schemas.scene.wall import WallCreate, WallResponse
from app.services.scene import object_service, opening_service, room_service, scene_version_service, wall_service


promote_router = APIRouter(prefix="/scene-drafts", tags=["scene-versions"])
scene_versions_router = APIRouter(prefix="/scene-versions", tags=["scene-versions"])
floor_scene_versions_router = APIRouter(prefix="/floors", tags=["scene-versions"])


@promote_router.post(
    "/{scene_draft_id}/promote",
    response_model=SceneVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft → Scene Version 승격",
)
def promote_scene_draft(
    payload: PromoteRequest,
    scene_draft_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneVersionResponse:
    return scene_version_service.promote(
        db, scene_draft_id=scene_draft_id, payload=payload, user=current_user
    )


@scene_versions_router.get(
    "/{version_id}",
    response_model=SceneVersionDetailResponse,
    summary="Scene Version 단건 조회 (rooms/walls/openings/objects 포함)",
)
def get_scene_version(
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneVersionDetailResponse:
    return scene_version_service.get_scene_version(
        db, version_id=version_id, user=current_user
    )


@scene_versions_router.post(
    "/{version_id}/rescale",
    response_model=SceneVersionDetailResponse,
    summary="확정본 전체 비례 재스케일 (실측 기반 스케일 보정)",
)
def rescale_scene_version(
    payload: SceneDraftRescaleRequest,
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneVersionDetailResponse:
    return scene_version_service.rescale_scene_version(
        db, version_id=version_id, current_user=current_user,
        factor=payload.factor, scale_source=payload.scale_source,
    )


@scene_versions_router.patch(
    "/{version_id}/set-current",
    response_model=SceneVersionResponse,
    summary="현재 활성 버전으로 설정 (같은 floor 의 다른 버전 false 처리)",
)
def set_current_scene_version(
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneVersionResponse:
    return scene_version_service.set_current(
        db, version_id=version_id, user=current_user
    )


@scene_versions_router.delete(
    "/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Scene Version 삭제 (children/patch_logs/rf_runs cascade)",
)
def delete_scene_version(
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    scene_version_service.delete_version(
        db, version_id=version_id, user=current_user
    )
    return None


@floor_scene_versions_router.get(
    "/{floor_id}/scene-versions",
    response_model=list[SceneVersionResponse],
    summary="층의 Scene Version 목록",
)
def list_scene_versions_by_floor(
    floor_id: UUID = Path(...),
    is_current: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SceneVersionResponse]:
    return scene_version_service.list_by_floor(
        db, floor_id=floor_id, user=current_user, is_current=is_current
    )


# ---------------------------------------------------------------------------
# §8 확정본 자식 리소스 신규 추가 (POST). 기존 PATCH/DELETE 는 각 엔티티 라우터에 위치.
# 명세서 §8 에는 누락돼있던 부분 — 프론트에서 확정 버전 위에 새 도형을 그리는
# 요구사항으로 추가됨. 변경 시 patch_log 자동 기록.
# ---------------------------------------------------------------------------


@scene_versions_router.post(
    "/{version_id}/walls",
    response_model=WallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="확정본 Scene Version 에 새 Wall 추가 (patch_log 자동 기록)",
)
def add_wall_to_version(
    payload: WallCreate,
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WallResponse:
    return wall_service.create_wall(
        db, scene_version_id=version_id, payload=payload, user=current_user
    )


@scene_versions_router.post(
    "/{version_id}/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="확정본 Scene Version 에 새 Room 추가 (patch_log 자동 기록)",
)
def add_room_to_version(
    payload: RoomCreate,
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoomResponse:
    return room_service.create_room(
        db, scene_version_id=version_id, payload=payload, user=current_user
    )


@scene_versions_router.post(
    "/{version_id}/openings",
    response_model=OpeningResponse,
    status_code=status.HTTP_201_CREATED,
    summary="확정본 Scene Version 에 새 Opening 추가 (patch_log 자동 기록)",
)
def add_opening_to_version(
    payload: OpeningCreate,
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OpeningResponse:
    return opening_service.create_opening(
        db, scene_version_id=version_id, payload=payload, user=current_user
    )


@scene_versions_router.post(
    "/{version_id}/objects",
    response_model=ObjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="확정본 Scene Version 에 새 Object 추가 (patch_log 자동 기록)",
)
def add_object_to_version(
    payload: ObjectCreate,
    version_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ObjectResponse:
    return object_service.create_object(
        db, scene_version_id=version_id, payload=payload, user=current_user
    )

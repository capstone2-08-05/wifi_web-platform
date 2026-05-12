"""Scene Version 라우터"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene_version import (
    PromoteRequest,
    SceneVersionDetailResponse,
    SceneVersionResponse,
)
from app.services import scene_version_service


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

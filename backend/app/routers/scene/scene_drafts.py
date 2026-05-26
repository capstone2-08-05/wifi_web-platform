"""
Scene Draft 라우터
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.scene.scene_draft import (
    SceneDraftCreateRequest,
    SceneDraftDetailResponse,
    SceneDraftRescaleRequest,
    SceneDraftSummaryResponse,
    SceneDraftUpdateRequest,
)
from app.services.scene import scene_draft_service

router = APIRouter(prefix="/scene-drafts", tags=["scene-drafts"])
floor_scene_drafts_router = APIRouter(prefix="/floors", tags=["scene-drafts"])


@floor_scene_drafts_router.post(
    "/{floor_id}/scene-drafts",
    response_model=SceneDraftDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="빈 Scene Draft 생성 (수동 도면 작성용 — AI 분석 안 함)",
)
def create_empty_scene_draft(
    payload: SceneDraftCreateRequest,
    floor_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneDraftDetailResponse:
    return scene_draft_service.create_empty_draft(
        db,
        floor_id=floor_id,
        source_mode=payload.source_mode,
        current_user=current_user,
    )


@router.get(
    "",
    response_model=PaginatedResponse[SceneDraftSummaryResponse],
    summary="Scene Draft 목록 조회",
)
def list_scene_drafts(
    project_id: str | None = Query(default=None),
    floor_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[SceneDraftSummaryResponse]:
    return scene_draft_service.list_scene_drafts(
        db,
        current_user,
        page=page,
        page_size=page_size,
        project_id=project_id,
        floor_id=floor_id,
        status=status,
    )

@router.get(
    "/{scene_draft_id}",
    response_model=SceneDraftDetailResponse,
    summary="Scene Draft 단건 조회 (rooms/walls/openings/objects 포함)",
)
def get_scene_draft(
    scene_draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneDraftDetailResponse:
    return scene_draft_service.get_scene_draft(db, scene_draft_id, current_user)


@router.patch(
    "/{scene_draft_id}",
    response_model=SceneDraftDetailResponse,
    summary="Scene Draft summary 갱신 (scale_ratio 등)",
)
def patch_scene_draft(
    payload: SceneDraftUpdateRequest,
    scene_draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneDraftDetailResponse:
    # 좌표 PATCH(/draft-walls, /draft-openings, ...) 와 묶여 호출됨 — 자식은 안 건드림.
    return scene_draft_service.update_scene_draft_summary(
        db,
        scene_draft_id,
        current_user,
        scale_ratio_m_per_px=payload.scale_ratio_m_per_px,
        scale_source=payload.scale_source,
    )


@router.post(
    "/{scene_draft_id}/rescale",
    response_model=SceneDraftDetailResponse,
    summary="SceneDraft 전체 비례 재스케일 (단일 트랜잭션)",
)
def rescale_scene_draft(
    payload: SceneDraftRescaleRequest,
    scene_draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneDraftDetailResponse:
    # walls·openings·rooms·objects + dependent metadata + summary scale_ratio 를 한 번에 ×factor.
    # 프론트의 N-PATCH 패턴을 단일 요청으로 통합 (대규모 도면에서 클라이언트 폭주 방지).
    return scene_draft_service.rescale_scene_draft(
        db,
        scene_draft_id,
        current_user,
        factor=payload.factor,
        scale_source=payload.scale_source,
    )


@router.delete(
    "/{scene_draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Scene Draft 삭제 (자식 cascade)",
)
def delete_scene_draft(
    scene_draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    scene_draft_service.delete_scene_draft(db, scene_draft_id, current_user)
    return None
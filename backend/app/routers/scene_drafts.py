"""
Scene Draft 라우터
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.scene_draft import SceneDraftDetailResponse, SceneDraftSummaryResponse
from app.services import scene_draft_service

router = APIRouter(prefix="/scene-drafts", tags=["scene-drafts"])


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
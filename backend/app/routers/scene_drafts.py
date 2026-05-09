"""
Scene Draft 라우터
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene_draft import SceneDraftDetailResponse
from app.services import scene_draft_service

router = APIRouter(prefix="/scene-drafts", tags=["scene-drafts"])


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
"""Draft Wall 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.draft_wall import (
    DraftWallCreate,
    DraftWallResponse,
    DraftWallUpdate,
)
from app.services import draft_wall_service


scene_draft_walls_router = APIRouter(prefix="/scene-drafts", tags=["draft-walls"])
draft_walls_router = APIRouter(prefix="/draft-walls", tags=["draft-walls"])


@scene_draft_walls_router.post(
    "/{scene_draft_id}/draft-walls",
    response_model=DraftWallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft wall 추가",
)
def create_draft_wall(
    payload: DraftWallCreate,
    scene_draft_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftWallResponse:
    return draft_wall_service.create_draft_wall(
        db, scene_draft_id=scene_draft_id, payload=payload, user=current_user
    )


@draft_walls_router.patch(
    "/{wall_id}",
    response_model=DraftWallResponse,
    summary="Draft wall 부분 수정",
)
def update_draft_wall(
    payload: DraftWallUpdate,
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftWallResponse:
    return draft_wall_service.update_draft_wall(
        db, wall_id=wall_id, payload=payload, user=current_user
    )


@draft_walls_router.delete(
    "/{wall_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Draft wall 삭제",
)
def delete_draft_wall(
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    draft_wall_service.delete_draft_wall(db, wall_id=wall_id, user=current_user)
    return None

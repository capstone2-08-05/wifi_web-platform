"""Draft Opening 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene.draft_opening import (
    DraftOpeningCreate,
    DraftOpeningResponse,
    DraftOpeningUpdate,
)
from app.services.scene import draft_opening_service


scene_draft_openings_router = APIRouter(
    prefix="/scene-drafts", tags=["draft-openings"]
)
draft_openings_router = APIRouter(prefix="/draft-openings", tags=["draft-openings"])


@scene_draft_openings_router.post(
    "/{scene_draft_id}/draft-openings",
    response_model=DraftOpeningResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft opening 추가",
)
def create_draft_opening(
    payload: DraftOpeningCreate,
    scene_draft_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftOpeningResponse:
    return draft_opening_service.create_draft_opening(
        db, scene_draft_id=scene_draft_id, payload=payload, user=current_user
    )


@draft_openings_router.patch(
    "/{opening_id}",
    response_model=DraftOpeningResponse,
    summary="Draft opening 부분 수정",
)
def update_draft_opening(
    payload: DraftOpeningUpdate,
    opening_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftOpeningResponse:
    return draft_opening_service.update_draft_opening(
        db, opening_id=opening_id, payload=payload, user=current_user
    )


@draft_openings_router.delete(
    "/{opening_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Draft opening 삭제",
)
def delete_draft_opening(
    opening_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    draft_opening_service.delete_draft_opening(
        db, opening_id=opening_id, user=current_user
    )
    return None

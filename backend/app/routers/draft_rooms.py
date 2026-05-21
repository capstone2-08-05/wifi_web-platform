"""Draft Room 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.draft_room import (
    DraftRoomCreate,
    DraftRoomResponse,
    DraftRoomUpdate,
)
from app.services.scene import draft_room_service


scene_draft_rooms_router = APIRouter(prefix="/scene-drafts", tags=["draft-rooms"])
draft_rooms_router = APIRouter(prefix="/draft-rooms", tags=["draft-rooms"])


@scene_draft_rooms_router.post(
    "/{scene_draft_id}/draft-rooms",
    response_model=DraftRoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft room 추가",
)
def create_draft_room(
    payload: DraftRoomCreate,
    scene_draft_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftRoomResponse:
    return draft_room_service.create_draft_room(
        db, scene_draft_id=scene_draft_id, payload=payload, user=current_user
    )


@draft_rooms_router.patch(
    "/{room_id}",
    response_model=DraftRoomResponse,
    summary="Draft room 부분 수정",
)
def update_draft_room(
    payload: DraftRoomUpdate,
    room_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftRoomResponse:
    return draft_room_service.update_draft_room(
        db, room_id=room_id, payload=payload, user=current_user
    )


@draft_rooms_router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Draft room 삭제",
)
def delete_draft_room(
    room_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    draft_room_service.delete_draft_room(db, room_id=room_id, user=current_user)
    return None

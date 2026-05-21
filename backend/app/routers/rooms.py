"""확정본 Room 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.room import RoomResponse, RoomUpdate
from app.services.scene import room_service


router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get(
    "/{room_id}",
    response_model=RoomResponse,
    summary="확정본 Room 단건 조회",
)
def get_room(
    room_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoomResponse:
    return room_service.get_room(db, room_id=room_id, user=current_user)


@router.patch(
    "/{room_id}",
    response_model=RoomResponse,
    summary="확정본 Room 부분 수정 (patch_log 자동 기록)",
)
def update_room(
    payload: RoomUpdate,
    room_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoomResponse:
    return room_service.update_room(
        db, room_id=room_id, payload=payload, user=current_user
    )


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="확정본 Room 삭제 (patch_log 자동 기록)",
)
def delete_room(
    room_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    room_service.delete_room(db, room_id=room_id, user=current_user)
    return None

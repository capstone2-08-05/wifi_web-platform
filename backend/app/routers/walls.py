"""확정본 Wall 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.wall import WallResponse, WallUpdate
from app.services.scene import wall_service


router = APIRouter(prefix="/walls", tags=["walls"])


@router.get(
    "/{wall_id}",
    response_model=WallResponse,
    summary="확정본 Wall 단건 조회",
)
def get_wall(
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WallResponse:
    return wall_service.get_wall(db, wall_id=wall_id, user=current_user)


@router.patch(
    "/{wall_id}",
    response_model=WallResponse,
    summary="확정본 Wall 부분 수정 (patch_log 자동 기록)",
)
def update_wall(
    payload: WallUpdate,
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WallResponse:
    return wall_service.update_wall(
        db, wall_id=wall_id, payload=payload, user=current_user
    )


@router.delete(
    "/{wall_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="확정본 Wall 삭제 (patch_log 자동 기록)",
)
def delete_wall(
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    wall_service.delete_wall(db, wall_id=wall_id, user=current_user)
    return None

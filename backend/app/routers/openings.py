"""확정본 Opening 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.opening import OpeningResponse, OpeningUpdate
from app.services import opening_service


router = APIRouter(prefix="/openings", tags=["openings"])


@router.get(
    "/{opening_id}",
    response_model=OpeningResponse,
    summary="확정본 Opening 단건 조회",
)
def get_opening(
    opening_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OpeningResponse:
    return opening_service.get_opening(
        db, opening_id=opening_id, user=current_user
    )


@router.patch(
    "/{opening_id}",
    response_model=OpeningResponse,
    summary="확정본 Opening 부분 수정 (patch_log 자동 기록)",
)
def update_opening(
    payload: OpeningUpdate,
    opening_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OpeningResponse:
    return opening_service.update_opening(
        db, opening_id=opening_id, payload=payload, user=current_user
    )


@router.delete(
    "/{opening_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="확정본 Opening 삭제 (patch_log 자동 기록)",
)
def delete_opening(
    opening_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    opening_service.delete_opening(
        db, opening_id=opening_id, user=current_user
    )
    return None

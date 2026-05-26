"""확정본 Object 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene.scene_object import ObjectResponse, ObjectUpdate
from app.services.scene import object_service


router = APIRouter(prefix="/objects", tags=["objects"])


@router.get(
    "/{object_id}",
    response_model=ObjectResponse,
    summary="확정본 Object 단건 조회",
)
def get_object(
    object_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ObjectResponse:
    return object_service.get_object(
        db, object_id=object_id, user=current_user
    )


@router.patch(
    "/{object_id}",
    response_model=ObjectResponse,
    summary="확정본 Object 부분 수정 (patch_log 자동 기록)",
)
def update_object(
    payload: ObjectUpdate,
    object_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ObjectResponse:
    return object_service.update_object(
        db, object_id=object_id, payload=payload, user=current_user
    )


@router.delete(
    "/{object_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="확정본 Object 삭제 (patch_log 자동 기록)",
)
def delete_object(
    object_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    object_service.delete_object(
        db, object_id=object_id, user=current_user
    )
    return None

"""Draft Object 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.draft_object import (
    DraftObjectCreate,
    DraftObjectResponse,
    DraftObjectUpdate,
)
from app.services import draft_object_service


scene_draft_objects_router = APIRouter(
    prefix="/scene-drafts", tags=["draft-objects"]
)
draft_objects_router = APIRouter(prefix="/draft-objects", tags=["draft-objects"])


@scene_draft_objects_router.post(
    "/{scene_draft_id}/draft-objects",
    response_model=DraftObjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft object 추가",
)
def create_draft_object(
    payload: DraftObjectCreate,
    scene_draft_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftObjectResponse:
    return draft_object_service.create_draft_object(
        db, scene_draft_id=scene_draft_id, payload=payload, user=current_user
    )


@draft_objects_router.patch(
    "/{object_id}",
    response_model=DraftObjectResponse,
    summary="Draft object 부분 수정",
)
def update_draft_object(
    payload: DraftObjectUpdate,
    object_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DraftObjectResponse:
    return draft_object_service.update_draft_object(
        db, object_id=object_id, payload=payload, user=current_user
    )


@draft_objects_router.delete(
    "/{object_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Draft object 삭제",
)
def delete_draft_object(
    object_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    draft_object_service.delete_draft_object(
        db, object_id=object_id, user=current_user
    )
    return None

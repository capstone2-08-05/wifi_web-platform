"""Patch Log 라우터"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.patch_log import PatchLogResponse
from app.services import patch_log_service


router = APIRouter(prefix="/scene-versions", tags=["patch-logs"])


@router.get(
    "/{version_id}/patch-logs",
    response_model=PaginatedResponse[PatchLogResponse],
    summary="Scene Version 의 수정 이력",
)
def list_patch_logs(
    version_id: UUID = Path(...),
    target_type: Optional[str] = Query(
        default=None, description="필터: room/wall/opening/object"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[PatchLogResponse]:
    return patch_log_service.list_patch_logs(
        db,
        version_id=version_id,
        user=current_user,
        page=page,
        page_size=page_size,
        target_type=target_type,
    )

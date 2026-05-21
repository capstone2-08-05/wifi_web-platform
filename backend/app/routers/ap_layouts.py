"""AP Layouts 라우터 (§14.3, §14.4)"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.ap_layout import (
    ApLayoutCreate,
    ApLayoutResponse,
    ApLayoutUpdate,
)
from app.services.rf import ap_layout_service


router = APIRouter(prefix="/ap-layouts", tags=["ap-layouts"])
rf_run_router = APIRouter(prefix="/rf-runs", tags=["ap-layouts"])


@rf_run_router.get(
    "/{rf_run_id}/ap-layouts",
    response_model=list[ApLayoutResponse],
    summary="RF Run 의 AP 배치 목록",
)
def list_ap_layouts(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApLayoutResponse]:
    return ap_layout_service.list_by_rf_run(
        db, rf_run_id=rf_run_id, user=current_user
    )


@router.post(
    "",
    response_model=ApLayoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="AP 배치 확정",
)
def create_ap_layout(
    payload: ApLayoutCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApLayoutResponse:
    return ap_layout_service.create_layout(db, payload=payload, user=current_user)


@router.get(
    "/{layout_id}",
    response_model=ApLayoutResponse,
    summary="AP 배치 단건 조회",
)
def get_ap_layout(
    layout_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApLayoutResponse:
    return ap_layout_service.get_layout(db, layout_id=layout_id, user=current_user)


@router.patch(
    "/{layout_id}",
    response_model=ApLayoutResponse,
    summary="AP 배치 수정",
)
def update_ap_layout(
    payload: ApLayoutUpdate,
    layout_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApLayoutResponse:
    return ap_layout_service.update_layout(
        db, layout_id=layout_id, payload=payload, user=current_user
    )


@router.delete(
    "/{layout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="AP 배치 삭제",
)
def delete_ap_layout(
    layout_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ap_layout_service.delete_layout(db, layout_id=layout_id, user=current_user)
    return None

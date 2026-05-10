"""RF Run 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.rf_map import RfMapResponse
from app.schemas.rf_run import RfRunCreate, RfRunCreatedResponse, RfRunResponse
from app.services import rf_run_service


router = APIRouter(prefix="/rf-runs", tags=["rf-runs"])


@router.post(
    "",
    response_model=RfRunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="RF 시뮬레이션 큐 등록",
)
def create_rf_run(
    payload: RfRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunCreatedResponse:
    return rf_run_service.create_rf_run(db, payload=payload, user=current_user)


@router.get(
    "/{rf_run_id}",
    response_model=RfRunResponse,
    summary="RF 실행 상태/결과 조회",
)
def get_rf_run(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunResponse:
    return rf_run_service.get_rf_run(db, rf_run_id=rf_run_id, user=current_user)


@router.get(
    "/{rf_run_id}/maps",
    response_model=list[RfMapResponse],
    summary="생성된 전파 맵 목록",
)
def list_rf_maps(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RfMapResponse]:
    return rf_run_service.list_maps(db, rf_run_id=rf_run_id, user=current_user)

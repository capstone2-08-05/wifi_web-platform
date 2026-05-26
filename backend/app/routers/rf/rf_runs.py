"""RF Run 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_internal_api_key
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.rf.rf_map import RfMapCreate, RfMapResponse
from app.schemas.rf.rf_run import (
    RfRunCreate,
    RfRunCreatedResponse,
    RfRunResponse,
    RfRunUpdate,
)
from app.services.rf import rf_run_service


router = APIRouter(prefix="/rf-runs", tags=["rf-runs"])
floor_rf_runs_router = APIRouter(prefix="/floors", tags=["rf-runs"])


@floor_rf_runs_router.get(
    "/{floor_id}/rf-runs",
    response_model=PaginatedResponse[RfRunResponse],
    summary="층의 RF Run 목록 (created_at desc, status 필터, 페이지네이션)",
)
def list_floor_rf_runs(
    floor_id: UUID = Path(...),
    status: str | None = Query(default=None, description="queued|running|completed|failed 등"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[RfRunResponse]:
    return rf_run_service.list_by_floor(
        db, floor_id=floor_id, user=current_user, page=page, page_size=page_size, status=status
    )


@router.post(
    "",
    response_model=RfRunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="RF 시뮬레이션 Job 등록 (access_points + simulation 주면 SageMaker async invoke). job_id 받아서 GET /rf-jobs/{job_id} 로 폴링.",
)
async def create_rf_run(
    payload: RfRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunCreatedResponse:
    return await rf_run_service.create_rf_run(db, payload=payload, user=current_user)


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


# ---------------------------------------------------------------------------
# 시스템 호출용 (AI 서버 → 백엔드)
# ---------------------------------------------------------------------------
@router.patch(
    "/{rf_run_id}",
    response_model=RfRunResponse,
    summary="[시스템] RF Run 상태/메트릭 갱신 (AI 서버용)",
    dependencies=[Depends(verify_internal_api_key)],
)
def update_rf_run(
    payload: RfRunUpdate,
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> RfRunResponse:
    return rf_run_service.update_rf_run(
        db, rf_run_id=rf_run_id, payload=payload
    )


@router.post(
    "/{rf_run_id}/maps",
    response_model=RfMapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[시스템] RF Map 결과 저장 (AI 서버용)",
    dependencies=[Depends(verify_internal_api_key)],
)
def create_rf_map(
    payload: RfMapCreate,
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> RfMapResponse:
    return rf_run_service.create_rf_map(
        db, rf_run_id=rf_run_id, payload=payload
    )

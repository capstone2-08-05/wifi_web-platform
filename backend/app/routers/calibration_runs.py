"""§11 Calibration 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_internal_api_key
from app.db.session import get_db
from app.models.user import User
from app.schemas.calibration_run import (
    CalibrationRunCreate,
    CalibrationRunResponse,
    CalibrationRunUpdate,
    ParameterUpdateCreate,
    ParameterUpdateResponse,
)
from app.services.rf import calibration_run_service


router = APIRouter(prefix="/calibration-runs", tags=["calibration"])


@router.post(
    "",
    response_model=CalibrationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="캘리브레이션 실행 (§11.1). RF 결과 vs 실측 비교 Job 큐 등록.",
)
def create_calibration_run(
    payload: CalibrationRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalibrationRunResponse:
    return calibration_run_service.create_calibration_run(
        db, payload=payload, user=current_user
    )


@router.get(
    "/{run_id}",
    response_model=CalibrationRunResponse,
    summary="캘리브레이션 결과 조회 (§11.2)",
)
def get_calibration_run(
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalibrationRunResponse:
    return calibration_run_service.get_calibration_run(
        db, run_id=run_id, user=current_user
    )


@router.get(
    "/{run_id}/parameter-updates",
    response_model=list[ParameterUpdateResponse],
    summary="파라미터 변경 이력 (§11.3)",
)
def list_parameter_updates(
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ParameterUpdateResponse]:
    return calibration_run_service.list_parameter_updates(
        db, run_id=run_id, user=current_user
    )


# ---------------------------------------------------------------------------
# 시스템 호출용 (AI 워커 → 백엔드)
# ---------------------------------------------------------------------------
@router.patch(
    "/{run_id}",
    response_model=CalibrationRunResponse,
    summary="[시스템] 캘리브레이션 상태/메트릭 갱신",
    dependencies=[Depends(verify_internal_api_key)],
)
def update_calibration_run(
    payload: CalibrationRunUpdate,
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> CalibrationRunResponse:
    return calibration_run_service.update_calibration_run(
        db, run_id=run_id, payload=payload
    )


@router.post(
    "/{run_id}/parameter-updates",
    response_model=ParameterUpdateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[시스템] 파라미터 변경 기록 추가",
    dependencies=[Depends(verify_internal_api_key)],
)
def create_parameter_update(
    payload: ParameterUpdateCreate,
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> ParameterUpdateResponse:
    return calibration_run_service.create_parameter_update(
        db, run_id=run_id, payload=payload
    )

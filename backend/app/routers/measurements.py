from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.measurement import (
    DetectedApResponseDTO,
    EstimatedCoverageResponseDTO,
    MeasurementLinkContextResponseDTO,
    MeasurementLinkCreateResponseDTO,
    MeasurementPointBatchRequestDTO,
    MeasurementPointBatchResponseDTO,
    MeasurementPointResponseDTO,
    MeasurementSessionCompleteRequestDTO,
    MeasurementSessionCompleteResponseDTO,
    MeasurementSessionCreateRequestDTO,
    MeasurementSessionResponseDTO,
)
from app.schemas.pagination import PaginatedResponse
from app.services.rf import measurement_service

router = APIRouter(tags=["measurement"])


@router.post(
    "/floors/{floor_id}/measurement-links",
    response_model=MeasurementLinkCreateResponseDTO,
)
def create_measurement_link(
    floor_id: str,
    db: Session = Depends(get_db),
) -> MeasurementLinkCreateResponseDTO:
    return measurement_service.create_measurement_link(db, floor_id)


@router.get(
    "/measurement-links/{token}/context",
    response_model=MeasurementLinkContextResponseDTO,
)
def get_measurement_link_context(
    token: str,
    db: Session = Depends(get_db),
) -> MeasurementLinkContextResponseDTO:
    return measurement_service.get_measurement_link_context(db, token)


@router.post(
    "/measurement-sessions",
    response_model=MeasurementSessionResponseDTO,
)
def create_measurement_session(
    body: MeasurementSessionCreateRequestDTO,
    db: Session = Depends(get_db),
) -> MeasurementSessionResponseDTO:
    return measurement_service.create_measurement_session(db, body)


@router.post(
    "/measurement-sessions/{session_id}/points",
    response_model=MeasurementPointBatchResponseDTO,
)
def upload_measurement_points(
    session_id: str,
    body: MeasurementPointBatchRequestDTO,
    db: Session = Depends(get_db),
) -> MeasurementPointBatchResponseDTO:
    return measurement_service.upload_measurement_points(db, session_id, body)


@router.post(
    "/measurement-sessions/{session_id}/complete",
    response_model=MeasurementSessionCompleteResponseDTO,
)
def complete_measurement_session(
    session_id: str,
    body: MeasurementSessionCompleteRequestDTO,
    db: Session = Depends(get_db),
) -> MeasurementSessionCompleteResponseDTO:
    return measurement_service.complete_measurement_session(db, session_id, body)


# ============================================================
# §10.4 / §10.5 — 웹에서 조회 (JWT, owner check)
# ============================================================
@router.get(
    "/measurement-sessions/{session_id}",
    response_model=MeasurementSessionResponseDTO,
    summary="측정 세션 단건 조회 (§10.4)",
)
def get_measurement_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MeasurementSessionResponseDTO:
    return measurement_service.get_session(db, session_id, current_user)


@router.get(
    "/measurement-sessions/{session_id}/points",
    response_model=PaginatedResponse[MeasurementPointResponseDTO],
    summary="세션 내 측정 포인트 목록 (§10.4, 페이지네이션)",
)
def list_measurement_points(
    session_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[MeasurementPointResponseDTO]:
    return measurement_service.list_points(
        db, session_id, current_user, page=page, page_size=page_size
    )


@router.get(
    "/floors/{floor_id}/measurement-sessions",
    response_model=PaginatedResponse[MeasurementSessionResponseDTO],
    summary="층의 측정 세션 목록 (§10.4)",
)
def list_floor_measurement_sessions(
    floor_id: str,
    status: str | None = Query(default=None, description="in_progress|completed 등 필터"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[MeasurementSessionResponseDTO]:
    return measurement_service.list_sessions_by_floor(
        db, floor_id, current_user, page=page, page_size=page_size, status=status
    )


@router.get(
    "/measurement-sessions/{session_id}/detected-aps",
    response_model=list[DetectedApResponseDTO],
    summary="세션 내 발견된 AP 목록 (§10.5)",
)
def list_detected_aps(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DetectedApResponseDTO]:
    return measurement_service.list_detected_aps(db, session_id, current_user)


@router.get(
    "/measurement-sessions/{session_id}/estimated-coverage",
    response_model=EstimatedCoverageResponseDTO,
    summary="GP regression 으로 측정점 → dense RSSI 맵 추정 (#81)",
)
def estimate_session_coverage(
    session_id: str,
    resolution_m: float = Query(default=0.5, gt=0.1, le=2.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EstimatedCoverageResponseDTO:
    return measurement_service.estimate_session_coverage(
        db, session_id, current_user, grid_resolution_m=resolution_m
    )

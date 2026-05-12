from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.measurement import (
    MeasurementLinkContextResponseDTO,
    MeasurementLinkCreateResponseDTO,
    MeasurementPointBatchRequestDTO,
    MeasurementPointBatchResponseDTO,
    MeasurementSessionCompleteRequestDTO,
    MeasurementSessionCompleteResponseDTO,
    MeasurementSessionCreateRequestDTO,
    MeasurementSessionResponseDTO,
)
from app.services import measurement_service

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

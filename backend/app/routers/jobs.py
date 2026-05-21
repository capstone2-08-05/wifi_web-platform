"""Job 라우터"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.job import JobResponse
from app.schemas.pagination import PaginatedResponse
from app.services.inference import job_service


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "",
    response_model=PaginatedResponse[JobResponse],
    summary="Job 목록 (job_type/status 필터)",
)
def list_jobs(
    job_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[JobResponse]:
    return job_service.list_jobs(
        db,
        user=current_user,
        page=page,
        page_size=page_size,
        job_type=job_type,
        status=status,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Job 단건 조회",
)
def get_job(
    job_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    return job_service.get_job(db, job_id=job_id, user=current_user)

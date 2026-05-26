"""도면 분석 Job 폴링 router.

GET /floorplan-jobs/{job_id} 한 endpoint 만 노출. 프론트가 주기적으로 호출 →
백엔드가 SageMaker 출력 S3 확인 → 완료/실패 시 그 트랜잭션에서 SceneDraft 까지 영속화.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.inference.job import JobResponse
from app.services.inference.floorplan_job_service import poll_floorplan_job

router = APIRouter(prefix="/floorplan-jobs", tags=["floorplan-jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="도면 분석 Job 상태 조회 (running 이면 S3 확인 후 완료 처리)",
)
async def get_floorplan_job(
    job_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    job = await poll_floorplan_job(
        db, job_id=str(job_id), current_user=current_user
    )
    return JobResponse.model_validate(job, from_attributes=True)

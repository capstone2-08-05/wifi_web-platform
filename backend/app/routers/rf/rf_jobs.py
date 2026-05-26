"""RF 시뮬레이션 Job 폴링 router.

GET /rf-jobs/{job_id} — 상태 조회. running 이면 S3 확인 후 완료/실패 처리.
POST /rf-jobs/{job_id}/refresh — 강제 폴링 (단일 호출로 S3 확인 → DB 갱신).

heatmap/radio_map URI 는 presigned URL 로도 함께 반환.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Job, User
from app.schemas.rf.rf_run import (
    RfJobError,
    RfJobOutputUri,
    RfJobResponse,
    RfRunCreatedResponse,
    RfRunResponse,
)
from app.services.rf.rf_job_service import poll_rf_job, retry_rf_job
from app.services.rf.sagemaker_rf_inference_service import sagemaker_rf_inference_service

router = APIRouter(prefix="/rf-jobs", tags=["rf-jobs"])


@router.get(
    "/{job_id}",
    response_model=RfJobResponse,
    summary="RF 시뮬레이션 Job 상태 조회 (running 이면 S3 확인 후 완료 처리)",
)
async def get_rf_job(
    job_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfJobResponse:
    job = await poll_rf_job(db, job_id=str(job_id), current_user=current_user)
    return _to_response(job)


@router.post(
    "/{job_id}/refresh",
    response_model=RfJobResponse,
    summary="RF 시뮬레이션 Job 강제 폴링 (GET 과 동일하지만 명시적)",
)
async def refresh_rf_job(
    job_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfJobResponse:
    job = await poll_rf_job(db, job_id=str(job_id), current_user=current_user)
    return _to_response(job)


@router.post(
    "/{job_id}/retry",
    response_model=RfRunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="실패한 RF Job 재제출 (원본 input 으로 새 Job/RfRun 생성)",
)
async def retry_rf_job_endpoint(
    job_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunCreatedResponse:
    rf_run, new_job = await retry_rf_job(
        db, job_id=str(job_id), current_user=current_user
    )
    summary = RfRunResponse(
        id=rf_run.id,
        project_id=rf_run.project_id,
        floor_id=rf_run.floor_id,
        scene_version_id=rf_run.scene_version_id,
        run_type=rf_run.run_type,
        status=rf_run.status,
        request_json=rf_run.request_json or {},
        metrics_json=rf_run.metrics_json or {},
        created_at=rf_run.created_at,
    )
    return RfRunCreatedResponse(**summary.model_dump(), job_id=new_job.id)


def _to_response(job: Job) -> RfJobResponse:
    sagemaker_meta = (job.input_json or {}).get("sagemaker") or {}
    output_prefix = sagemaker_meta.get("output_prefix")
    result_json = job.result_json or {}

    heatmap_uri = result_json.get("heatmap_s3_uri")
    radio_uri = result_json.get("radio_map_s3_uri")
    rf_run_id = result_json.get("rf_run_id") or (job.input_json or {}).get("rf_run_id")
    error_obj = result_json.get("error")

    heatmap = _build_output_uri(heatmap_uri)
    radio_map = _build_output_uri(radio_uri)

    return RfJobResponse(
        job_id=job.id,
        rf_run_id=rf_run_id,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        output_prefix=output_prefix,
        result=result_json.get("radio_map_meta") if job.status == "done" else None,
        heatmap=heatmap,
        radio_map=radio_map,
        error=RfJobError(**error_obj) if error_obj else None,
    )


def _build_output_uri(s3_uri: str | None) -> RfJobOutputUri | None:
    if not s3_uri:
        return None
    try:
        url = sagemaker_rf_inference_service.presigned_url(s3_uri)
    except Exception:
        url = None
    return RfJobOutputUri(s3_uri=s3_uri, url=url)

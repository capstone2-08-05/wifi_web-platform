"""RF 시뮬레이션 Job (job_type='rf_simulate') 오케스트레이션.

비동기 Job 패턴 (AI 의 floorplan_job_service 와 동일 구조):
  - submit_rf_simulation: SceneVersion → scene.json + SageMaker invoke + Job/RfRun row 생성
  - poll_rf_job: status=running 이면 S3 결과 확인 후 마무리
  - _complete_rf_job: result.json 다운로드 → RfRun.metrics_json 갱신 + Job.result_json 갱신

폴링은 호출자(GET /rf-jobs/{job_id} 또는 background task)가 주기적으로 한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import Job, Project, RfRun, SceneVersion, User
from app.models.rf_map import RfMap
from app.services.rf.sagemaker_rf_inference_service import (
    SageMakerRfInferenceFailure,
    map_rf_failure_to_app_error,
    sagemaker_rf_inference_service,
)
from app.services.scene.scene_version_export import export_scene_version_to_scene_json

logger = logging.getLogger(__name__)

JOB_TYPE_RF_SIMULATE = "rf_simulate"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


# ============================================================
# Submit
# ============================================================
async def submit_rf_simulation(
    db: Session,
    *,
    scene_version_id: UUID,
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    current_user: User,
    run_type: str = "rf_simulate",
    metadata: dict[str, Any] | None = None,
) -> tuple[RfRun, Job]:
    """SceneVersion 확인 + scene.json export + SageMaker submit + Job/RfRun row 생성.

    반환: (rf_run, job) — 둘 다 commit 완료된 상태.
    """
    sv = _get_owned_scene_version(db, scene_version_id, current_user)

    # 1) scene.json 빌드 (DB → dict)
    try:
        scene_json = export_scene_version_to_scene_json(db, sv.id)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            ErrorCode.SCENE_VERSION_EXPORT_FAILED,
            f"Failed to build scene.json from SceneVersion {sv.id}: {exc}",
            500,
        ) from exc

    # 2) SageMaker submit (블록 X)
    submit_result = await sagemaker_rf_inference_service.submit(
        scene_json=scene_json,
        project_id=str(sv.project_id),
        floor_id=str(sv.floor_id),
        scene_version_id=str(sv.id),
        simulation=simulation,
        access_points=access_points,
        metadata={
            **(metadata or {}),
            "requested_by": current_user.email,
            "source": "web-platform",
        },
    )

    now = _now_utc()

    # 3) RfRun row
    rf_run = RfRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        run_type=run_type,
        status=JOB_STATUS_RUNNING,
        request_json={
            "access_points": access_points,
            "simulation": simulation,
            "metadata": metadata or {},
        },
        metrics_json={},
    )

    # 4) Job row (input_json 에 sagemaker meta 보관 — AI 패턴과 동일)
    input_json: dict[str, Any] = {
        "rf_run_id": None,  # rf_run.id 는 flush 후 채움
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "requested_by": current_user.email,
        "sagemaker": {
            "inference_id": submit_result.sagemaker_inference_id,
            "scene_s3_uri": submit_result.scene_s3_uri,
            "input_s3_uri": submit_result.input_s3_uri,
            "output_prefix": submit_result.output_prefix,
            "sagemaker_output_location": submit_result.sagemaker_output_location,
            "sagemaker_failure_location": submit_result.sagemaker_failure_location,
        },
    }
    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type=JOB_TYPE_RF_SIMULATE,
        status=JOB_STATUS_RUNNING,
        input_json=input_json,
        result_json={},
        started_at=now,
    )

    try:
        db.add(rf_run)
        db.flush()  # rf_run.id 확보
        input_json["rf_run_id"] = rf_run.id
        job.input_json = input_json
        db.add(job)
        db.commit()
        db.refresh(rf_run)
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to persist RF simulation job: {exc}",
            500,
        ) from exc

    logger.info(
        "RF job submitted job_id=%s rf_run_id=%s sagemaker_inference_id=%s",
        job.id, rf_run.id, submit_result.sagemaker_inference_id,
    )
    return rf_run, job


# ============================================================
# Poll & complete
# ============================================================
async def retry_rf_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> tuple[RfRun, Job]:
    """실패한 RF Job 을 동일 input 으로 재제출 → 새 Job/RfRun 생성.

    원본 Job 은 그대로 두고 새 row 를 만든다. 입력 (scene_version_id, access_points,
    simulation, metadata) 은 원본 Job.input_json 에서 그대로 가져옴.

    failed 상태가 아닌 Job 을 retry 하면 409 (충돌). 단, retryable=true 가 아닌
    실패도 사용자가 명시적으로 재시도하면 허용 (운영 판단).
    """
    job = _get_owned_rf_job_or_404(db, job_id, current_user)
    if job.status != JOB_STATUS_FAILED:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"Cannot retry job in status '{job.status}'. Only failed jobs can be retried.",
            status_code=409,
        )

    input_meta = job.input_json or {}
    scene_version_id = input_meta.get("scene_version_id")
    access_points = input_meta.get("access_points")
    simulation = input_meta.get("simulation")
    if not scene_version_id or not access_points or not simulation:
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Cannot retry: original Job.input_json missing scene_version_id / access_points / simulation.",
            500,
        )

    metadata = input_meta.get("metadata") or {}
    metadata["retry_of_job_id"] = str(job.id)

    return await submit_rf_simulation(
        db,
        scene_version_id=UUID(str(scene_version_id)),
        access_points=access_points,
        simulation=simulation,
        current_user=current_user,
        metadata=metadata,
    )


async def poll_rf_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> Job:
    """RF Job 조회 + (running 이면 S3 확인) + 완료/실패 시 본 트랜잭션에서 마무리.

    AI 패턴과 동일: race-safe 를 위해 finalize 직전 row lock + status 재확인.
    """
    job = _get_owned_rf_job_or_404(db, job_id, current_user)

    if job.status != JOB_STATUS_RUNNING:
        return job

    sagemaker_meta = (job.input_json or {}).get("sagemaker") or {}
    output_prefix = sagemaker_meta.get("output_prefix")
    sagemaker_failure_location = sagemaker_meta.get("sagemaker_failure_location") or ""
    if not output_prefix:
        return _claim_and_finalize(
            db, str(job.id), current_user,
            finalize=lambda l: _mark_job_failed(
                db, l,
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                stage="validate_input",
                message="Job.input_json.sagemaker.output_prefix missing",
            ),
        )

    status = await run_in_threadpool(
        sagemaker_rf_inference_service.check_status,
        output_prefix,
        sagemaker_failure_location=sagemaker_failure_location,
    )

    if status == "running":
        return job

    if status == "infra_failed":
        return _claim_and_finalize(
            db, str(job.id), current_user,
            finalize=lambda l: _mark_job_failed(
                db, l,
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                stage="sagemaker_infra",
                message=f"SageMaker infrastructure error (see {sagemaker_failure_location})",
            ),
        )

    if status == "failed":
        failure = await run_in_threadpool(
            sagemaker_rf_inference_service.download_failure, output_prefix
        )
        return _claim_and_finalize(
            db, str(job.id), current_user,
            finalize=lambda l: _mark_job_failed_from_container(db, l, failure),
        )

    # status == "completed"
    return await _complete_rf_job(db, job, output_prefix)


# ============================================================
# Internal: 완료 처리 / 실패 처리
# ============================================================
async def _complete_rf_job(db: Session, job: Job, output_prefix: str) -> Job:
    inference = await run_in_threadpool(
        sagemaker_rf_inference_service.download_result,
        str(job.id),
        output_prefix,
    )

    # race-safe: row lock 잡고 재확인
    locked = _lock_job(db, str(job.id))
    if locked.status != JOB_STATUS_RUNNING:
        return locked

    # 연관 RfRun 찾아서 metrics_json 갱신 + RfMap row 자동 생성
    rf_run = _find_associated_rf_run(db, locked)
    if rf_run is not None:
        rf_run.status = JOB_STATUS_DONE
        rf_run.metrics_json = {
            "radio_map": inference.result_payload.get("radio_map") or {},
            "runtime": inference.result_payload.get("runtime") or {},
            "stages": inference.result_payload.get("stages") or {},
            "outputs": inference.result_payload.get("outputs") or {},
        }
        _create_rf_map_rows(db, rf_run, inference)

    locked.status = JOB_STATUS_DONE
    locked.result_json = {
        "rf_run_id": rf_run.id if rf_run is not None else None,
        "result_s3_uri": inference.result_s3_uri,
        "heatmap_s3_uri": inference.heatmap_s3_uri,
        "radio_map_s3_uri": inference.radio_map_s3_uri,
        "radio_map_meta": inference.result_payload.get("radio_map") or {},
    }
    locked.error_message = None
    locked.finished_at = _now_utc()

    try:
        db.commit()
        db.refresh(locked)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark RF job done: {exc}",
            500,
        ) from exc

    logger.info(
        "RF job done job_id=%s rf_run_id=%s heatmap=%s",
        locked.id, (rf_run.id if rf_run else None), inference.heatmap_s3_uri,
    )
    return locked


def _mark_job_failed_from_container(
    db: Session, job: Job, failure: SageMakerRfInferenceFailure
) -> Job:
    app_error = map_rf_failure_to_app_error(failure)
    return _mark_job_failed(
        db, job,
        code=app_error.code,
        stage=failure.stage,
        message=failure.message,
        container_code=failure.code,
        details=failure.details,
    )


def _mark_job_failed(
    db: Session,
    job: Job,
    *,
    code: ErrorCode,
    stage: str,
    message: str,
    container_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> Job:
    job.status = JOB_STATUS_FAILED
    job.error_message = f"[{stage}] {message}"
    job.result_json = {
        "error": {
            "backend_code": str(code),
            "container_code": container_code,
            "stage": stage,
            "message": message,
            "retryable": (details or {}).get("retryable", False),
            "details": details or {},
        },
    }
    job.finished_at = _now_utc()

    rf_run = _find_associated_rf_run(db, job)
    if rf_run is not None:
        rf_run.status = JOB_STATUS_FAILED

    try:
        db.commit()
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark RF job failed: {exc}",
            500,
        ) from exc

    logger.warning(
        "RF job failed job_id=%s code=%s stage=%s message=%s",
        job.id, code, stage, message,
    )
    return job


# ============================================================
# Helpers
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_owned_scene_version(
    db: Session, scene_version_id: UUID, user: User
) -> SceneVersion:
    stmt = (
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(scene_version_id),
            Project.owner_user_id == user.id,
        )
    )
    sv = db.execute(stmt).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            404,
        )
    return sv


def _get_owned_rf_job_or_404(
    db: Session, job_id: str, current_user: User
) -> Job:
    stmt = (
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(
            Job.id == str(job_id),
            Job.job_type == JOB_TYPE_RF_SIMULATE,
            Project.owner_user_id == current_user.id,
        )
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, "RF simulation job not found.", 404)
    return job


def _lock_job(db: Session, job_id: str) -> Job:
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    return db.execute(stmt).scalar_one()


def _claim_and_finalize(db: Session, job_id: str, current_user: User, *, finalize) -> Job:
    locked = _lock_job(db, job_id)
    if locked.status != JOB_STATUS_RUNNING:
        return locked
    return finalize(locked)


def _find_associated_rf_run(db: Session, job: Job) -> RfRun | None:
    """Job.input_json.rf_run_id 로 RfRun 1건 찾음."""
    rf_run_id = (job.input_json or {}).get("rf_run_id")
    if not rf_run_id:
        return None
    return db.execute(
        select(RfRun).where(RfRun.id == str(rf_run_id))
    ).scalar_one_or_none()


def _create_rf_map_rows(db: Session, rf_run: RfRun, inference) -> None:
    """RF 시뮬 결과 → RfMap row 자동 생성.

    heatmap.png 와 radio_map.npy 각각 한 row 씩 추가. storage_url 은 s3:// URI.
    프론트는 GET /rf-runs/{id}/maps 로 받아서 presigned URL 만들거나 직접 사용.
    """
    radio_meta = inference.result_payload.get("radio_map") or {}
    bounds = radio_meta.get("bounds_m") or {}
    cell_size_m = float(radio_meta.get("cell_size_m") or 0.5)
    resolution_cm = max(1, int(round(cell_size_m * 100)))

    metrics = {
        "rss_dbm": radio_meta.get("rss_dbm") or {},
        "coverage_summary": radio_meta.get("coverage_summary") or {},
        "valid_cell_count": radio_meta.get("valid_cell_count"),
        "invalid_cell_count": radio_meta.get("invalid_cell_count"),
        "valid_ratio": radio_meta.get("valid_ratio"),
        "grid_shape": radio_meta.get("grid_shape"),
    }

    if inference.heatmap_s3_uri:
        db.add(
            RfMap(
                rf_run_id=rf_run.id,
                map_type="heatmap",
                resolution_cm=resolution_cm,
                storage_url=inference.heatmap_s3_uri,
                bounds_json=bounds,
                metrics_json=metrics,
            )
        )
    if inference.radio_map_s3_uri:
        db.add(
            RfMap(
                rf_run_id=rf_run.id,
                map_type="radio_map_dbm",
                resolution_cm=resolution_cm,
                storage_url=inference.radio_map_s3_uri,
                bounds_json=bounds,
                metrics_json=metrics,
            )
        )

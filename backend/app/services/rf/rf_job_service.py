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
from app.core.geom import geojson_to_wkb
from app.models import Job, Project, RfRun, SceneVersion, User
from app.models.ap_layout import ApLayout
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

RF_BACKEND_SAGEMAKER = "sagemaker"
RF_BACKEND_LOCAL = "local"

RF_REQUEST_METADATA_KEYS = (
    "physical_aps_snapshot",
    "band_metadata",
    "coverage_semantics",
    "normalization_warnings",
)


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
    apply_calibration: bool = True,
    backend: str = RF_BACKEND_SAGEMAKER,
    _prebuilt_scene_json: dict[str, Any] | None = None,
    _prebuilt_calibration_meta: dict[str, Any] | None = None,
) -> tuple[RfRun, Job]:
    """SceneVersion 확인 + scene.json export + 백엔드로 submit + Job/RfRun row 생성.

    apply_calibration=True 면 해당 scene_version 의 최신 completed CalibrationRun
    보정값을 scene_json/simulation 에 미리 반영한다 (#88).

    _prebuilt_scene_json: 미리 빌드된 (보정값 적용 완료) scene.json.
      같은 scene_version으로 여러 번 제출할 때 중복 DB 조회/빌드를 피한다.
      이 값을 전달할 때는 apply_calibration=False 도 함께 전달해야 한다
      (보정은 사전 계산 시 이미 적용됐으므로 중복 방지).
    _prebuilt_calibration_meta: 사전 계산된 보정 메타. request_json 기록용.

    backend:
      - "sagemaker" (기본): S3 + invoke_endpoint_async, /rf-jobs/{id} 폴링으로 완료 확인
      - "local":           로컬 ai_api `/internal/sionna/run` 호출 (백그라운드 thread).
                            poll 은 DB status 만 읽음 — 외부 호출 X.

    반환: (rf_run, job) — 둘 다 commit 완료된 상태.
    """
    if backend not in {RF_BACKEND_SAGEMAKER, RF_BACKEND_LOCAL}:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"Unsupported RF backend: {backend!r}. "
            f"Allowed: {RF_BACKEND_SAGEMAKER}, {RF_BACKEND_LOCAL}",
            400,
        )

    sv = _get_owned_scene_version(db, scene_version_id, current_user)

    # 1) scene.json 빌드 (사전 계산값 있으면 재사용)
    if _prebuilt_scene_json is not None:
        scene_json = _prebuilt_scene_json
    else:
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

    # 1.5) calibration 보정값 반영 (사전 계산값 있으면 메타만 재사용)
    if _prebuilt_calibration_meta is not None:
        calibration_meta = _prebuilt_calibration_meta
    else:
        calibration_meta = {"applied": False}
        if apply_calibration:
            from app.services.rf.calibration_worker.apply import (
                apply_to_scene_and_sim,
                get_latest_calibration,
            )

            cr = get_latest_calibration(db, str(sv.id))
            if cr is not None:
                best_params = (cr.metrics_json or {}).get("best_params") or {}
                if best_params:
                    summary = apply_to_scene_and_sim(scene_json, simulation, best_params)
                    calibration_meta = {
                        "applied": True,
                        "calibration_run_id": cr.id,
                        "summary": summary,
                    }

    if backend == RF_BACKEND_LOCAL:
        from app.services.rf.rf_backend_local import submit_via_local_ai_api

        return await submit_via_local_ai_api(
            db,
            sv=sv,
            scene_json=scene_json,
            access_points=access_points,
            simulation=simulation,
            current_user=current_user,
            run_type=run_type,
            metadata=metadata,
            calibration_meta=calibration_meta,
        )

    return await _submit_via_sagemaker(
        db,
        sv=sv,
        scene_json=scene_json,
        access_points=access_points,
        simulation=simulation,
        current_user=current_user,
        run_type=run_type,
        metadata=metadata,
        calibration_meta=calibration_meta,
    )


async def _submit_via_sagemaker(
    db: Session,
    *,
    sv: SceneVersion,
    scene_json: dict[str, Any],
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    current_user: User,
    run_type: str,
    metadata: dict[str, Any] | None,
    calibration_meta: dict[str, Any],
) -> tuple[RfRun, Job]:
    """SageMaker async backend: scene/input 을 S3 에 올리고 invoke_endpoint_async."""
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
            "calibration": calibration_meta,
            "backend": RF_BACKEND_SAGEMAKER,
            **_request_metadata_fields(metadata),
        },
        metrics_json={},
    )

    input_json: dict[str, Any] = {
        "rf_run_id": None,  # rf_run.id 는 flush 후 채움
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "metadata": metadata or {},
        "requested_by": current_user.email,
        "backend": RF_BACKEND_SAGEMAKER,
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
        # request_json.access_points → ApLayout row 들 자동 생성 (#measurement 페이지 표시).
        # 사용자가 시뮬 페이지에서 찍은 AP 좌표를 다른 페이지 (측정/진단) 에서도 보려면 필요.
        if run_type != "ap_recommendation_verify":
            create_ap_layouts_from_request(db, rf_run, access_points)
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
        "RF job submitted (sagemaker) job_id=%s rf_run_id=%s sagemaker_inference_id=%s",
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
    original_backend = input_meta.get("backend") or RF_BACKEND_SAGEMAKER

    return await submit_rf_simulation(
        db,
        scene_version_id=UUID(str(scene_version_id)),
        access_points=access_points,
        simulation=simulation,
        current_user=current_user,
        metadata=metadata,
        backend=original_backend,
    )


async def poll_rf_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> Job:
    """RF Job 조회 + 완료/실패 시 본 트랜잭션에서 마무리.

    backend 별 분기:
      - sagemaker: running 이면 S3 확인 후 완료/실패 처리 (race-safe row lock + status 재확인)
      - local:     백그라운드 thread 가 직접 DB 를 업데이트하므로 DB read 만 함.
    """
    job = _get_owned_rf_job_or_404(db, job_id, current_user)

    if job.status != JOB_STATUS_RUNNING:
        return job

    backend = (job.input_json or {}).get("backend") or RF_BACKEND_SAGEMAKER
    if backend == RF_BACKEND_LOCAL:
        # 백그라운드 thread 가 완료시 DB 직접 업데이트 — 폴링은 단순 read.
        # 세션 캐시 회피 위해 refresh.
        db.refresh(job)
        # 좀비 감지: daemon=True 스레드는 서버 재시작 시 사망 → job 이 영원히 running.
        # ai_api 타임아웃 600s + overhead = 정상 완료 최대 ~15분.
        # 20분 이상 running 이면 스레드가 죽은 것으로 간주하고 failed 처리.
        if job.status == JOB_STATUS_RUNNING and job.started_at:
            elapsed = (datetime.now(timezone.utc) - job.started_at).total_seconds()
            if elapsed > 1200:
                job.status = JOB_STATUS_FAILED
                job.error_message = (
                    "[local_ai_api] zombie: background thread likely died on server restart"
                )
                job.finished_at = _now_utc()
                rf_run_id = (job.input_json or {}).get("rf_run_id")
                if rf_run_id:
                    rf_run_row = db.execute(
                        select(RfRun).where(RfRun.id == rf_run_id)
                    ).scalar_one_or_none()
                    if rf_run_row is not None:
                        rf_run_row.status = JOB_STATUS_FAILED
                try:
                    db.commit()
                    logger.warning(
                        "RF job %s marked failed (zombie detection): ran >20min without completion",
                        job.id,
                    )
                except SQLAlchemyError:
                    db.rollback()
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
        radio_map = inference.result_payload.get("radio_map") or {}
        # 검증 run 이면 저장된 affine 보정값 적용해 calibrated_values_dbm 추가
        affine_meta: dict[str, Any] = {}
        raw_values = radio_map.get("values_dbm")
        if raw_values and rf_run.run_type == "ap_recommendation_verify":
            from app.services.rf.calibration_worker.apply import (
                get_latest_affine_calibration,
                apply_affine_to_values,
            )
            affine = get_latest_affine_calibration(db, str(rf_run.floor_id))
            if affine:
                radio_map["calibrated_values_dbm"] = apply_affine_to_values(
                    raw_values, affine["slope"], affine["intercept_db"]
                )
                affine_meta = {"applied": True, **affine}
            else:
                affine_meta = {"applied": False}
        rf_run.metrics_json = {
            "radio_map": radio_map,
            "runtime": inference.result_payload.get("runtime") or {},
            "stages": inference.result_payload.get("stages") or {},
            "outputs": inference.result_payload.get("outputs") or {},
            "affine_calibration": affine_meta,
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


def _request_metadata_fields(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {key: metadata[key] for key in RF_REQUEST_METADATA_KEYS if key in metadata}


def create_ap_layouts_from_request(
    db: Session, rf_run: RfRun, access_points: list[dict[str, Any]],
) -> None:
    """access_points 리스트 → ApLayout row 들 일괄 add (commit 은 호출자 책임).

    데이터 모델 정리: rf_run.request_json.access_points 와 ap_layouts 테이블이
    중복으로 같은 정보 보관 중. 이 함수가 submit 시점에 ap_layouts 도 같이 채워서
    측정/진단 페이지가 일관되게 AP 마커 표시 가능.

    fallback 동작: x/y 누락된 entry 는 skip. 빈 access_points 는 no-op.
    """
    if not access_points:
        return
    for i, ap in enumerate(access_points):
        x = ap.get("x_m") if ap.get("x_m") is not None else ap.get("x")
        y = ap.get("y_m") if ap.get("y_m") is not None else ap.get("y")
        if x is None or y is None:
            continue
        z = ap.get("z_m") if ap.get("z_m") is not None else ap.get("z")
        ap_id = str(ap.get("id") or f"ap{i + 1}")
        try:
            point_geom = geojson_to_wkb(
                {"type": "Point", "coordinates": [float(x), float(y)]},
                "Point",
                "ap_layout.point_geom",
            )
        except AppError:
            # 좌표 파싱 실패는 silent skip — 시뮬 자체는 진행되도록.
            continue
        db.add(
            ApLayout(
                rf_run_id=rf_run.id,
                ap_name=ap_id,
                point_geom=point_geom,
                z_m=float(z) if z is not None else 2.5,
                power_dbm=float(ap["power_dbm"]) if ap.get("power_dbm") is not None else None,
            )
        )


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

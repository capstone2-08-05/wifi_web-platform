"""도면 분석 Job (job_type='floorplan_analyze') 오케스트레이션.

비동기 Job 패턴:
  - submit_floorplan_analysis: SageMaker invoke + Job row 생성 (status=running)
  - poll_floorplan_job: Job 조회 + (running 이면 S3 확인) + 완료 시 변환/저장

폴링은 호출자(=백엔드 GET 엔드포인트 또는 background task) 가 주기적으로 한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AppError, ErrorCode
from app.models import Asset, Floor, Job, Project, User
from app.schemas.scene_draft import (
    SaveSceneDraftRequestDTO,
    UploadStorageMetadataDTO,
)
from app.services.asset_service import create_floorplan_asset_from_bytes
from app.services.fusion_service import fusion_service
from app.services.sagemaker_inference_service import (
    SageMakerInferenceFailure,
    map_failure_to_app_error,
    sagemaker_inference_service,
)
from app.services.scene_draft_service import _resolve_project_floor, save_scene_draft

logger = logging.getLogger(__name__)

JOB_TYPE_FLOORPLAN_ANALYZE = "floorplan_analyze"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


# ============================================================
# Submit
# ============================================================
async def submit_floorplan_analysis(
    db: Session,
    *,
    image_bytes: bytes,
    filename: str,
    content_type: str,
    real_width_m: float,
    project_id: str | None,
    floor_id: str | None,
    current_user: User,
    upload_metadata: UploadStorageMetadataDTO,
    created_by: str | None = None,
    source_asset_id: str | None = None,
) -> Job:
    """SageMaker submit + Job row 생성. 1~3초 안에 반환.

    source_asset_id 가 None 이면 이 Job 이 분석할 원본 도면을 assets 테이블에 자동
    등록한다 (raw upload 흐름). analyze_from_asset 처럼 이미 asset 이 있는 경우는
    호출자가 그 id 를 명시적으로 넘겨야 중복 생성을 막을 수 있다.

    저장된 source_asset_id 는 Job.input_json 에 보관되어 _complete_floorplan_job
    에서 asset.metadata_json 백필 + SceneDraft.source_asset_id 전파에 쓰인다.
    """
    resolved_project_id, resolved_floor_id = _resolve_project_floor(
        db, project_id, floor_id, current_user
    )

    # raw upload 경로면 여기서 asset row 를 만들어 둔다. floor 단위 도면 자산이
    # 항상 존재해야 measurement_link 가 그걸 가리킬 수 있다.
    if source_asset_id is None:
        new_asset = create_floorplan_asset_from_bytes(
            db,
            project_id=resolved_project_id,
            floor_id=resolved_floor_id,
            content=image_bytes,
            filename=filename,
            content_type=content_type,
            uploaded_by=current_user.id,
        )
        source_asset_id = new_asset.id
        # upload_metadata 에 실제 S3 좌표도 같이 보관 (참조 용이)
        if not upload_metadata.s3_uri:
            try:
                upload_metadata = upload_metadata.model_copy(
                    update={
                        "provider": upload_metadata.provider or "s3",
                        "s3_uri": new_asset.storage_url,
                    }
                )
            except Exception:
                pass

    submit_result = await sagemaker_inference_service.submit(
        image_bytes=image_bytes,
        filename=filename,
        project_id=resolved_project_id,
        floor_id=resolved_floor_id,
        content_type=content_type,
    )

    input_json: dict[str, Any] = {
        "filename": filename,
        "content_type": content_type,
        "real_width_m": real_width_m,
        "created_by": created_by or current_user.email,
        "source_asset_id": source_asset_id,
        "upload": upload_metadata.model_dump(),
        "sagemaker": {
            "inference_id": submit_result.sagemaker_inference_id,
            "source_s3_uri": submit_result.source_s3_uri,
            "input_s3_uri": submit_result.input_s3_uri,
            "output_prefix": submit_result.output_prefix,
            "sagemaker_output_location": submit_result.sagemaker_output_location,
            "sagemaker_failure_location": submit_result.sagemaker_failure_location,
        },
    }

    job = Job(
        project_id=resolved_project_id,
        floor_id=resolved_floor_id,
        job_type=JOB_TYPE_FLOORPLAN_ANALYZE,
        status=JOB_STATUS_RUNNING,
        input_json=input_json,
        result_json={},
        started_at=_now_utc(),
    )

    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to persist floorplan analysis job: {exc}",
            500,
        ) from exc

    logger.info(
        "Floorplan job submitted job_id=%s sagemaker_inference_id=%s",
        job.id,
        submit_result.sagemaker_inference_id,
    )
    return job


# ============================================================
# Poll & complete
# ============================================================
async def poll_floorplan_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> Job:
    """Job 조회. status=running 이면 S3 결과 확인 → 완료/실패 시 본 트랜잭션에서 마무리.

    동시 폴링 안전성:
      - 비싼 S3/CPU 작업은 lock 없이 진행 (race window 허용)
      - 최종 DB write 직전에 `with_for_update()` 로 row lock 잡고 status 재확인
      - 이미 다른 poller 가 완료/실패 처리했다면 그 결과를 그대로 반환 (idempotent)
    """
    job = _get_owned_floorplan_job_or_404(db, job_id, current_user)

    if job.status != JOB_STATUS_RUNNING:
        return job

    sagemaker_meta = (job.input_json or {}).get("sagemaker") or {}
    output_prefix = sagemaker_meta.get("output_prefix")
    sagemaker_failure_location = sagemaker_meta.get("sagemaker_failure_location") or ""
    if not output_prefix:
        # 잘못 등록된 Job — 진행 불가
        return _mark_job_failed(
            db,
            job,
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            stage="validate_input",
            message="Job.input_json.sagemaker.output_prefix missing",
        )

    # boto3 는 blocking → threadpool 로 이벤트 루프 보호
    status = await run_in_threadpool(
        sagemaker_inference_service.check_status,
        output_prefix,
        sagemaker_failure_location=sagemaker_failure_location,
    )

    if status == "running":
        return job

    if status == "infra_failed":
        return _claim_and_finalize(
            db,
            job_id,
            current_user,
            finalize=lambda locked: _mark_job_failed(
                db,
                locked,
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                stage="sagemaker_infra",
                message=f"SageMaker infrastructure error (see {sagemaker_failure_location})",
            ),
        )

    if status == "failed":
        failure = await run_in_threadpool(
            sagemaker_inference_service.download_failure, output_prefix
        )
        return _claim_and_finalize(
            db,
            job_id,
            current_user,
            finalize=lambda locked: _mark_job_failed_from_container(db, locked, failure),
        )

    # status == "completed"
    return await _complete_floorplan_job(db, job, current_user, output_prefix)


# ============================================================
# Internal: 완료 처리 / 실패 처리
# ============================================================
async def _complete_floorplan_job(
    db: Session,
    job: Job,
    current_user: User,
    output_prefix: str,
) -> Job:
    source_s3_uri = (job.input_json or {}).get("sagemaker", {}).get("source_s3_uri")
    inference = await run_in_threadpool(
        sagemaker_inference_service.download_result,
        str(job.id),
        output_prefix,
        source_s3_uri,
    )

    input_meta = job.input_json or {}
    real_width_m = float(input_meta.get("real_width_m", 10.0))
    filename = str(input_meta.get("filename") or "floorplan.png")
    upload_meta = input_meta.get("upload") or {}
    created_by = input_meta.get("created_by")

    try:
        scene = await fusion_service.build_scene_from_inference(
            result=inference,
            filename=filename,
            real_width_m=real_width_m,
        )

        # race-safe: row lock 잡고 status 재확인. 다른 poller 가 이미 done/failed 라면 그대로 반환.
        locked = _lock_job(db, str(job.id))
        if locked.status != JOB_STATUS_RUNNING:
            return locked

        source_asset_id = (locked.input_json or {}).get("source_asset_id")

        # 측정 흐름이 asset.metadata_json 에서 width/height/scale 을 읽기 때문에
        # 분석 결과가 나오는 이 시점에 같이 채워둬야 모바일 context 의 bounds 가 정상.
        if source_asset_id:
            _backfill_asset_spatial_metadata(db, source_asset_id, scene)

        request_dto = SaveSceneDraftRequestDTO(
            scene=scene,
            upload=UploadStorageMetadataDTO(**upload_meta) if upload_meta else UploadStorageMetadataDTO(),
            project_id=locked.project_id,
            floor_id=locked.floor_id,
            created_by=created_by,
        )
        save_result = save_scene_draft(
            db, request_dto, current_user, source_asset_id=source_asset_id
        )
    except SageMakerInferenceFailure as failure:
        # build 중에 발생할 일은 거의 없지만 방어적으로
        return _claim_and_finalize(
            db,
            str(job.id),
            current_user,
            finalize=lambda l: _mark_job_failed_from_container(db, l, failure),
        )
    except AppError as exc:
        return _claim_and_finalize(
            db,
            str(job.id),
            current_user,
            finalize=lambda l: _mark_job_failed(
                db, l, code=exc.code, stage="scene_build", message=exc.message
            ),
        )
    except Exception as exc:
        logger.exception("Unexpected error completing floorplan job %s", job.id)
        return _claim_and_finalize(
            db,
            str(job.id),
            current_user,
            finalize=lambda l: _mark_job_failed(
                db,
                l,
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                stage="scene_build",
                message=f"unexpected error: {exc}",
            ),
        )
    finally:
        inference.cleanup()

    # 성공 — Job 마무리 (locked 위에서 잡혀 있음, 같은 트랜잭션)
    locked.status = JOB_STATUS_DONE
    locked.result_json = {
        "scene_draft_id": save_result.scene_draft_id,
        "scale_ratio_m_per_px": scene.scale_ratio,
        "counts": {
            "walls": len(scene.walls),
            "openings": len(scene.openings),
            "objects": len(scene.objects),
            "rooms": len(scene.rooms),
        },
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
            f"Failed to mark floorplan job done: {exc}",
            500,
        ) from exc
    logger.info("Floorplan job done job_id=%s scene_draft_id=%s", locked.id, save_result.scene_draft_id)
    return locked


def _mark_job_failed_from_container(
    db: Session, job: Job, failure: SageMakerInferenceFailure
) -> Job:
    """컨테이너 측 failure.json → Job 실패 처리."""
    app_error = map_failure_to_app_error(failure)
    return _mark_job_failed(
        db,
        job,
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
            "details": details or {},
        },
    }
    job.finished_at = _now_utc()
    try:
        db.commit()
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark floorplan job failed: {exc}",
            500,
        ) from exc
    logger.warning(
        "Floorplan job failed job_id=%s code=%s stage=%s message=%s",
        job.id,
        code,
        stage,
        message,
    )
    return job


# ============================================================
# Helpers
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _backfill_asset_spatial_metadata(db: Session, asset_id: str, scene: Any) -> None:
    """분석 결과에서 얻은 도면 픽셀 차원/스케일을 asset.metadata_json 에 머지.

    measurement_service._bounds_from_floorplan 이 width_px/height_px/scale_m_per_px
    중 하나라도 None 이면 빈 bounds 를 반환하기 때문에 이 백필이 누락되면 모바일
    measurement context 가 도면 url 만 있고 좌표 frame 이 없는 상태가 된다.

    JSONB 컬럼은 dict 내부 변경을 SQLAlchemy 가 감지하지 못해 flag_modified 가 필요.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        logger.warning("backfill skipped: asset %s not found", asset_id)
        return

    image_meta = getattr(scene, "inference_metadata", None) or {}
    if not isinstance(image_meta, dict):
        image_meta = {}
    image = image_meta.get("image") or {}
    width = image.get("width_px")
    height = image.get("height_px")
    scale = getattr(scene, "scale_ratio", None)

    md: dict[str, Any] = dict(asset.metadata_json or {})
    changed = False
    if width is not None and md.get("width_px") != width:
        md["width_px"] = int(width)
        changed = True
    if height is not None and md.get("height_px") != height:
        md["height_px"] = int(height)
        changed = True
    if scale is not None:
        scale_f = float(scale)
        if md.get("scale_m_per_px") != scale_f:
            md["scale_m_per_px"] = scale_f
            changed = True

    if changed:
        asset.metadata_json = md
        flag_modified(asset, "metadata_json")
        logger.info(
            "asset %s spatial metadata backfilled: w=%s h=%s scale=%s",
            asset_id, md.get("width_px"), md.get("height_px"), md.get("scale_m_per_px"),
        )


def _get_owned_floorplan_job_or_404(
    db: Session, job_id: str, current_user: User
) -> Job:
    stmt = (
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(
            Job.id == str(job_id),
            Job.job_type == JOB_TYPE_FLOORPLAN_ANALYZE,
            Project.owner_user_id == current_user.id,
        )
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, "Floorplan analysis job not found.", 404)
    return job


def _lock_job(db: Session, job_id: str) -> Job:
    """SELECT ... FOR UPDATE 로 Job row lock 획득. 같은 row 에 대한 동시 poller 직렬화.

    인증/소유권 확인은 이미 _get_owned_floorplan_job_or_404 에서 끝났다고 가정.
    """
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    return db.execute(stmt).scalar_one()


def _claim_and_finalize(
    db: Session,
    job_id: str,
    current_user: User,
    *,
    finalize,
) -> Job:
    """동시 폴링 시 중복 실패 처리 방지. row lock 후 상태 재확인 → 아직 running 일 때만 finalize 호출."""
    locked = _lock_job(db, job_id)
    if locked.status != JOB_STATUS_RUNNING:
        return locked
    return finalize(locked)

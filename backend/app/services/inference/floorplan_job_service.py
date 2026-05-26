"""도면 분석 Job (job_type='floorplan_analyze') 오케스트레이션.

비동기 Job 패턴:
  - submit_floorplan_analysis: SageMaker invoke + Job row 생성 (status=running)
  - poll_floorplan_job: Job 조회 + (running 이면 S3 확인) + 완료 시 변환/저장

폴링은 호출자(=백엔드 GET 엔드포인트 또는 background task) 가 주기적으로 한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AppError, ErrorCode
from app.db.session import SessionLocal
from app.models import Asset, Floor, Job, Project, User
from app.schemas.scene.scene_draft import (
    SaveSceneDraftRequestDTO,
    UploadStorageMetadataDTO,
)
from app.core.settings import ai_service_url
from app.services.asset_service import (
    create_floorplan_asset_from_bytes,
    create_floorplan_asset_from_local_path,
)
from app.services.floorplan.fusion_service import fusion_service
from app.services.inference.local_inference_service import run_local_inference
from app.services.inference.sagemaker_inference_service import (
    InferenceResult,
    SageMakerInferenceFailure,
    map_failure_to_app_error,
    sagemaker_inference_service,
)
from app.services.scene.scene_draft_service import _resolve_project_floor, save_scene_draft

logger = logging.getLogger(__name__)

JOB_TYPE_FLOORPLAN_ANALYZE = "floorplan_analyze"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"

INFERENCE_MODE_SAGEMAKER = "sagemaker"
INFERENCE_MODE_LOCAL = "local"


# ============================================================
# Submit
# ============================================================
async def submit_floorplan_analysis(
    db: Session,
    *,
    image_bytes: bytes,
    filename: str,
    content_type: str,
    project_id: str | None,
    floor_id: str | None,
    current_user: User,
    upload_metadata: UploadStorageMetadataDTO,
    created_by: str | None = None,
    source_asset_id: str | None = None,
    inference_mode: str = INFERENCE_MODE_SAGEMAKER,
) -> Job:
    """SageMaker submit + Job row 생성. 1~3초 안에 반환.

    source_asset_id 가 None 이면 이 Job 이 분석할 원본 도면을 assets 테이블에 자동
    등록한다 (raw upload 흐름). analyze_from_asset 처럼 이미 asset 이 있는 경우는
    호출자가 그 id 를 명시적으로 넘겨야 중복 생성을 막을 수 있다.

    저장된 source_asset_id 는 Job.input_json 에 보관되어 _complete_floorplan_job
    에서 asset.metadata_json 백필 + SceneDraft.source_asset_id 전파에 쓰인다.

    inference_mode:
      - "sagemaker" (기본): S3 + async invocation + 폴링
      - "local": `AI_SERVICE_URL` 동기 호출 → 즉시 fusion+save → done 으로 반환
    """
    if inference_mode not in (INFERENCE_MODE_SAGEMAKER, INFERENCE_MODE_LOCAL):
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Unknown inference_mode: {inference_mode}",
            400,
        )

    resolved_project_id, resolved_floor_id = _resolve_project_floor(
        db, project_id, floor_id, current_user
    )

    # raw upload 경로면 여기서 asset row 를 만들어 둔다. floor 단위 도면 자산이
    # 항상 존재해야 measurement_link 가 그걸 가리킬 수 있다.
    # SageMaker 모드: S3 PUT + storage_url=s3://...
    # 로컬 모드 (개발용): S3 우회 + storage_url=file:///local/path (router 가 이미 저장한 파일)
    if source_asset_id is None:
        if inference_mode == INFERENCE_MODE_SAGEMAKER:
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
        elif inference_mode == INFERENCE_MODE_LOCAL:
            # router(_validate_and_save_file) 가 이미 UPLOAD_DIR 에 저장 → 그 경로 사용.
            local_path = upload_metadata.local_saved_path
            if not local_path:
                raise AppError(
                    ErrorCode.INTERNAL_SERVER_ERROR,
                    "Local inference mode requires upload.local_saved_path",
                    500,
                )
            new_asset = create_floorplan_asset_from_local_path(
                db,
                project_id=resolved_project_id,
                floor_id=resolved_floor_id,
                local_path=local_path,
                filename=filename,
                content_type=content_type,
                file_size_bytes=upload_metadata.size_bytes or len(image_bytes),
                uploaded_by=current_user.id,
            )
            source_asset_id = new_asset.id

    # ── 로컬 모드: Job 생성 + 백그라운드 task 등록 → 202 즉시 반환 ─────────────
    # SageMaker 흐름과 동일하게 프론트는 폴링으로 완료 확인.
    if inference_mode == INFERENCE_MODE_LOCAL:
        input_json_local: dict[str, Any] = {
            "filename": filename,
            "content_type": content_type,
            "created_by": created_by or current_user.email,
            "source_asset_id": source_asset_id,
            "upload": upload_metadata.model_dump(),
            "inference_mode": INFERENCE_MODE_LOCAL,
            "ai_service_url": ai_service_url(),
        }
        job = Job(
            project_id=resolved_project_id,
            floor_id=resolved_floor_id,
            job_type=JOB_TYPE_FLOORPLAN_ANALYZE,
            status=JOB_STATUS_RUNNING,
            input_json=input_json_local,
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
                f"Failed to persist floorplan analysis job (local): {exc}",
                500,
            ) from exc

        logger.info("Floorplan job (local) submitted job_id=%s", job.id)

        # 백그라운드에서 inference + finalize. 요청 핸들러는 즉시 반환 (job=running).
        # asyncio.create_task 는 핸들러 반환 후에도 살아 있음 — 자체 DB 세션 사용 필수.
        asyncio.create_task(
            _run_local_in_background(
                job_id=str(job.id),
                owner_user_id=current_user.id,
                image_bytes=image_bytes,
                filename=filename,
                content_type=content_type,
            ),
            name=f"local-inference-{job.id}",
        )
        return job

    # ── SageMaker 모드 (기본) ────────────────────────────────────────────────
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
        "created_by": created_by or current_user.email,
        "source_asset_id": source_asset_id,
        "upload": upload_metadata.model_dump(),
        "inference_mode": INFERENCE_MODE_SAGEMAKER,
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

    # 로컬 모드 Job 은 `submit_floorplan_analysis` 가 동기적으로 finalize 함.
    # 폴링 시점에 아직 running 이면 (a) submit 핸들러가 진행 중 또는 (b) submit 중간에
    # 죽어 stale 상태. 어느 쪽이든 poller 가 할 일 없음 — 현재 상태 그대로 반환.
    input_meta = job.input_json or {}
    if input_meta.get("inference_mode") == INFERENCE_MODE_LOCAL:
        return job

    sagemaker_meta = input_meta.get("sagemaker") or {}
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
    return await _finalize_with_inference(db, job, current_user, inference)


async def _run_local_in_background(
    *,
    job_id: str,
    owner_user_id: str,
    image_bytes: bytes,
    filename: str,
    content_type: str,
) -> None:
    """로컬 inference + finalize 를 백그라운드 task 로 실행.

    submit 핸들러는 Job row 만들고 즉시 반환했으므로 여기서 자체 DB 세션을 새로
    열어 finalize. 실패하면 Job 을 failed 로 마크.
    """
    logger.info("local bg task: ENTER job_id=%s", job_id)
    db: Session = SessionLocal()
    try:
        owner = db.get(User, owner_user_id)
        job = db.get(Job, job_id)
        if owner is None or job is None:
            logger.warning(
                "local bg task: missing owner(%s) or job(%s), skip",
                owner_user_id, job_id,
            )
            return

        # 1) 로컬 AI 호출 (blocking HTTP) — threadpool 로 이벤트 루프 보호
        try:
            inference = await run_in_threadpool(
                run_local_inference,
                image_bytes=image_bytes,
                filename=filename,
                content_type=content_type,
                ai_service_url=ai_service_url(),
            )
        except AppError as exc:
            logger.warning(
                "local bg task: inference failed job_id=%s code=%s msg=%s",
                job_id, exc.code, exc.message,
            )
            _claim_and_finalize(
                db, job_id, owner,
                finalize=lambda l: _mark_job_failed(
                    db, l, code=exc.code, stage="local_inference", message=exc.message,
                ),
            )
            return
        except Exception as exc:
            logger.exception("local bg task: unexpected inference error job_id=%s", job_id)
            _claim_and_finalize(
                db, job_id, owner,
                finalize=lambda l: _mark_job_failed(
                    db, l,
                    code=ErrorCode.INTERNAL_SERVER_ERROR,
                    stage="local_inference",
                    message=f"unexpected error: {exc}",
                ),
            )
            return

        logger.info("local bg task: inference done, starting finalize job_id=%s", job_id)

        # 2) fusion + save + Job done — SageMaker 완료 경로와 100% 공유
        try:
            await _finalize_with_inference(db, job, owner, inference)
            logger.info("local bg task: finalize done job_id=%s", job_id)
        except Exception:
            logger.exception("local bg task: finalize failed job_id=%s", job_id)
    finally:
        db.close()
        logger.info("local bg task: EXIT job_id=%s", job_id)


async def _finalize_with_inference(
    db: Session,
    job: Job,
    current_user: User,
    inference: InferenceResult,
) -> Job:
    """다운로드된 InferenceResult 를 받아 fusion + save_scene_draft + Job done 마무리.

    SageMaker (다운로드 후) 와 로컬 모드 (즉시 호출 후) 양쪽에서 공유.
    """
    input_meta = job.input_json or {}
    filename = str(input_meta.get("filename") or "floorplan.png")
    upload_meta = input_meta.get("upload") or {}
    created_by = input_meta.get("created_by")

    try:
        scene = await fusion_service.build_scene_from_inference(
            result=inference,
            filename=filename,
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

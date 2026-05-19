"""RF 시뮬레이션 Job (job_type='rf_simulate') 오케스트레이션.

흐름 (ai_api 동기 호출 + background task):
  - submit_rf_simulation: SceneVersion → scene.json + Job/RfRun row 생성 + background task 스폰
  - 백그라운드 태스크가 ai_api Sionna 호출 → values_dbm 받아 matplotlib PNG 렌더링 →
    로컬 저장소 + RfMap row + RfRun/Job done

기존 SageMaker 비동기 패턴 (S3 polling) 은 제거됨. ai_api 가 단일 AP 만 받기 때문에
multi-AP 케이스는 첫 AP 만 시뮬 (현 한계, 추후 N회 호출 + 합성으로 확장).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.db.session import SessionLocal
from app.models import Job, Project, RfRun, SceneVersion, User
from app.models.rf_map import RfMap
from app.services import _local_storage as _storage
from app.services import ai_inference_client
from app.services.ai_inference_client import _SionnaCallInputs
from app.services.sagemaker_rf_inference_service import (
    SageMakerRfInferenceFailure,
    map_rf_failure_to_app_error,
)
from app.services.scene_version_export import export_scene_version_to_scene_json

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

    now = _now_utc()

    # 2) RfRun row
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

    # 3) Job row
    input_json: dict[str, Any] = {
        "rf_run_id": None,
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "requested_by": current_user.email,
        "ai_api": {
            "engine": "sionna_rt",
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
        db.flush()
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

    # 4) ai_api 호출은 background task 로
    asyncio.create_task(
        _run_rf_pipeline_in_background(
            job_id=str(job.id),
            rf_run_id=str(rf_run.id),
            scene_json=scene_json,
            access_points=access_points,
            simulation=simulation,
            floor_id=str(sv.floor_id),
        )
    )

    logger.info("RF job submitted job_id=%s rf_run_id=%s", job.id, rf_run.id)
    return rf_run, job


# ============================================================
# Background pipeline (ai_api Sionna 호출 + PNG 렌더링 + RfMap 저장)
# ============================================================
async def _run_rf_pipeline_in_background(
    *,
    job_id: str,
    rf_run_id: str,
    scene_json: dict[str, Any],
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    floor_id: str,
) -> None:
    """ai_api Sionna 호출 → values_dbm 받아 PNG 렌더 + RfMap row 생성 + Job done."""
    db = SessionLocal()
    try:
        try:
            ai_scene = _convert_scene_to_ai_api(scene_json)
            if not access_points:
                raise AppError(
                    ErrorCode.INVALID_REQUEST_BODY,
                    "RF simulation requires at least 1 access point.",
                    400,
                )
            # ai_api 는 단일 AP 만 받음 — 첫 AP 사용. multi-AP 는 추후 N회 호출 + 합성.
            ap_dict = access_points[0]
            ai_ap = _convert_ap_to_ai_api(ap_dict)
            ai_plane = _build_measurement_plane(scene_json, simulation)
            ai_sim = _build_sionna_sim_section(simulation)

            inputs = _SionnaCallInputs(
                scene=ai_scene,
                access_point=ai_ap,
                measurement_plane=ai_plane,
                simulation=ai_sim,
                floor_id=floor_id,
                run_type="run",
            )
            _, artifacts = await ai_inference_client.simulate_rf(
                job_id=job_id, inputs=inputs,
            )
        except SageMakerRfInferenceFailure as failure:
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed_from_container(db, job, failure)
            return
        except AppError as exc:
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job, code=exc.code, stage="ai_api_call", message=exc.message,
                )
            return
        except Exception as exc:
            logger.exception("ai_api Sionna call failed for job %s", job_id)
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job,
                    code=ErrorCode.INTERNAL_SERVER_ERROR,
                    stage="ai_api_call",
                    message=f"Unexpected ai_api error: {exc}",
                )
            return

        # values_dbm → PNG + RfMap row
        try:
            heatmap_uri, radio_map_uri, render_meta = _render_and_save_rf_outputs(
                artifacts, rf_run_id
            )
        except Exception as exc:
            logger.exception("RF render failed for job %s", job_id)
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job,
                    code=ErrorCode.INTERNAL_SERVER_ERROR,
                    stage="render_outputs",
                    message=f"Failed to render RF outputs: {exc}",
                )
            return

        _finalize_rf_job(
            db,
            job_id=job_id,
            rf_run_id=rf_run_id,
            artifacts=artifacts,
            heatmap_uri=heatmap_uri,
            radio_map_uri=radio_map_uri,
            render_meta=render_meta,
        )
    finally:
        db.close()


# ----- 변환 헬퍼 (legacy scene.json → ai_api FloorScene) -----
def _convert_scene_to_ai_api(scene_json: dict[str, Any]) -> dict[str, Any]:
    """legacy scene_json {walls: [{x1,y1,x2,y2,...}], rooms: [{points}]} →
    ai_api FloorScene {walls: [{id, start_xy, end_xy, ...}], rooms: [{id, polygon_xy}], ...}.
    """
    walls_out: list[dict[str, Any]] = []
    for i, w in enumerate(scene_json.get("walls") or []):
        walls_out.append({
            "id": f"w{i}",
            "start_xy": [float(w.get("x1", 0.0)), float(w.get("y1", 0.0))],
            "end_xy": [float(w.get("x2", 0.0)), float(w.get("y2", 0.0))],
            "thickness_m": float(w.get("thickness") or 0.12),
            "height_m": float(w.get("height") or 2.6),
            "material_id": str(w.get("material") or "concrete"),
        })

    rooms_out: list[dict[str, Any]] = []
    for i, r in enumerate(scene_json.get("rooms") or []):
        pts = r.get("points") or r.get("polygon_xy") or []
        if len(pts) >= 3:
            rooms_out.append({
                "id": f"r{i}",
                "polygon_xy": [[float(p[0]), float(p[1])] for p in pts],
            })

    return {
        "walls": walls_out,
        "openings": [],
        "rooms": rooms_out,
        "furniture": [],
    }


def _convert_ap_to_ai_api(ap: dict[str, Any]) -> dict[str, Any]:
    """legacy access_point dict → ai_api AccessPoint.

    legacy 키: {x, y, z?, tx_power_dbm?, frequency_ghz?, name?}
    ai_api 키: {id, position_m, tx_power_dbm?, frequency_ghz?, name?}
    """
    x = float(ap.get("x") or ap.get("position", [0, 0, 0])[0])
    y = float(ap.get("y") or ap.get("position", [0, 0, 0])[1])
    z = float(ap.get("z") or ap.get("z_m") or 2.5)
    out: dict[str, Any] = {
        "id": str(ap.get("id") or ap.get("name") or "ap1"),
        "position_m": [x, y, z],
        "name": ap.get("name"),
    }
    if ap.get("tx_power_dbm") is not None:
        out["tx_power_dbm"] = float(ap["tx_power_dbm"])
    if ap.get("frequency_ghz") is not None:
        out["frequency_ghz"] = float(ap["frequency_ghz"])
    return out


def _build_measurement_plane(
    scene_json: dict[str, Any], simulation: dict[str, Any]
) -> dict[str, Any]:
    z_m = float(simulation.get("measurement_z_m") or 1.0)
    cell_size_m = float(simulation.get("cell_size_m") or 0.25)
    return {"z_m": z_m, "cell_size_m": cell_size_m}


def _build_sionna_sim_section(simulation: dict[str, Any]) -> dict[str, Any]:
    """legacy simulation dict → ai_api simulation 객체. 빈 값들은 ai_api default 사용."""
    out: dict[str, Any] = {}
    if "physical" in simulation:
        out["physical"] = simulation["physical"]
    if "propagation" in simulation:
        out["propagation"] = simulation["propagation"]
    if "solver" in simulation:
        out["solver"] = simulation["solver"]
    return out


# ----- 결과 렌더링 (values_dbm → PNG + npy → 로컬 저장) -----
def _render_and_save_rf_outputs(
    artifacts: dict[str, Any], rf_run_id: str
) -> tuple[str, str, dict[str, Any]]:
    """ai_api artifacts.radiomap.values_dbm → heatmap.png + radio_map.npy (로컬 저장)."""
    radiomap = artifacts.get("radiomap") or {}
    values = radiomap.get("values_dbm")
    if not values:
        raise AppError(
            ErrorCode.RF_SIMULATION_FAILED,
            "ai_api Sionna response missing artifacts.radiomap.values_dbm",
            502,
        )
    arr = np.asarray(values, dtype=np.float32)
    bounds = radiomap.get("bounds_m") or {}

    # heatmap PNG (matplotlib jet, 자동 vmin/vmax)
    png_bytes = _render_heatmap_png(arr, bounds)
    npy_buf = io.BytesIO()
    np.save(npy_buf, arr)

    heatmap_key = f"rf-heatmaps/{rf_run_id}/heatmap.png"
    radio_map_key = f"rf-heatmaps/{rf_run_id}/radio_map.npy"

    heatmap_uri = _storage.upload_bytes(heatmap_key, png_bytes, content_type="image/png")
    radio_map_uri = _storage.upload_bytes(
        radio_map_key, npy_buf.getvalue(), content_type="application/octet-stream"
    )

    render_meta = {
        "grid_shape": list(arr.shape),
        "bounds_m": bounds,
        "min_dbm": float(arr.min()) if arr.size > 0 else None,
        "max_dbm": float(arr.max()) if arr.size > 0 else None,
        "mean_dbm": float(arr.mean()) if arr.size > 0 else None,
    }
    return heatmap_uri, radio_map_uri, render_meta


def _render_heatmap_png(arr: np.ndarray, bounds: dict[str, Any]) -> bytes:
    """matplotlib 으로 RSSI heatmap PNG 생성."""
    # lazy import — matplotlib 무거움
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    extent = None
    if bounds:
        extent = (
            float(bounds.get("min_x", 0.0)),
            float(bounds.get("max_x", arr.shape[1])),
            float(bounds.get("min_y", 0.0)),
            float(bounds.get("max_y", arr.shape[0])),
        )

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(
        arr, cmap="jet", origin="lower",
        extent=extent, interpolation="bilinear",
    )
    fig.colorbar(im, ax=ax, label="RSSI (dBm)")
    ax.set_title("Sionna RT RSSI Heatmap")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _finalize_rf_job(
    db: Session,
    *,
    job_id: str,
    rf_run_id: str,
    artifacts: dict[str, Any],
    heatmap_uri: str,
    radio_map_uri: str,
    render_meta: dict[str, Any],
) -> None:
    """Job + RfRun done 마킹 + RfMap row 2개 생성. race-safe."""
    locked = _lock_job(db, job_id)
    if locked.status != JOB_STATUS_RUNNING:
        return

    rf_run = db.get(RfRun, rf_run_id)
    if rf_run is not None:
        rf_run.status = JOB_STATUS_DONE
        rf_run.metrics_json = {
            "radiomap": {
                "grid_shape": render_meta["grid_shape"],
                "bounds_m": render_meta["bounds_m"],
            },
            "rssi": {
                "min": render_meta["min_dbm"],
                "max": render_meta["max_dbm"],
                "mean": render_meta["mean_dbm"],
            },
            "ai_api_metrics": artifacts.get("rssi") or {},
            "coverage": artifacts.get("coverage") or {},
            "valid_ratio": artifacts.get("valid_ratio"),
        }

        cell_size_m = 0.25
        bounds = render_meta["bounds_m"] or {}
        # bounds + grid_shape 로부터 cell size 추정
        shape = render_meta["grid_shape"]
        if bounds and len(shape) == 2 and shape[1] > 0:
            cell_size_m = (
                float(bounds.get("max_x", 0)) - float(bounds.get("min_x", 0))
            ) / float(shape[1])
        resolution_cm = max(1, int(round(cell_size_m * 100)))

        metrics = {
            "grid_shape": render_meta["grid_shape"],
            "min_dbm": render_meta["min_dbm"],
            "max_dbm": render_meta["max_dbm"],
            "mean_dbm": render_meta["mean_dbm"],
        }
        db.add(RfMap(
            rf_run_id=rf_run.id, map_type="heatmap",
            resolution_cm=resolution_cm, storage_url=heatmap_uri,
            bounds_json=bounds, metrics_json=metrics,
        ))
        db.add(RfMap(
            rf_run_id=rf_run.id, map_type="radio_map_dbm",
            resolution_cm=resolution_cm, storage_url=radio_map_uri,
            bounds_json=bounds, metrics_json=metrics,
        ))

    locked.status = JOB_STATUS_DONE
    locked.result_json = {
        "rf_run_id": rf_run_id,
        "heatmap_url": _storage.static_url(heatmap_uri),
        "radio_map_url": _storage.static_url(radio_map_uri),
        "grid_shape": render_meta["grid_shape"],
    }
    locked.error_message = None
    locked.finished_at = _now_utc()
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark RF job done: {exc}",
            500,
        ) from exc
    logger.info("RF job done job_id=%s rf_run_id=%s", job_id, rf_run_id)


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
    """RF Job 조회만. ai_api 흐름에서는 background task 가 마무리한다."""
    return _get_owned_rf_job_or_404(db, job_id, current_user)


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


# DEPRECATED (AWS 회귀 시 복원): RfMap row 자동 생성은 이제 _finalize_rf_job 가 직접 수행.
# 옛 SageMaker 흐름의 (s3:// URI 기반) 생성기로, 함수 자체는 보존만 한다.
def _create_rf_map_rows(db: Session, rf_run: RfRun, inference) -> None:
    raise NotImplementedError(
        "Legacy SageMaker RfMap creation disabled. See _finalize_rf_job instead."
    )

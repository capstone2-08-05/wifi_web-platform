"""Local ai_api backend for RF simulate (alternative to SageMaker async).

SageMaker 경로 대안: 로컬에서 띄운 ai_api 의 `/internal/sionna/run` 을 직접 호출.

핵심 차이:
  - SageMaker: submit 이 비동기로 S3 에 invoke, poll 로 결과 확인
  - Local:     submit 이 백그라운드 thread 에 ai_api 호출을 띄움 (Sionna 자체는
               분 단위 블로킹), 호출 완료 시 thread 가 직접 DB 업데이트.
               poll_rf_job 은 DB status 만 읽으면 됨 (외부 호출 X).

세션 관리: 백그라운드 thread 는 요청 세션을 못 쓰므로 `SessionLocal()` 로 새 세션 생성.

결과 매핑 (SageMaker 결과 구조에 최대한 맞춤 — 프론트가 동일 응답 형태로 받음):
  Job.result_json = {
      "rf_run_id": ..., "backend": "local",
      "heatmap_s3_uri": <imageUrl, http://...>,   # 같은 키 이름 재사용
      "radio_map_s3_uri": None,                   # 로컬은 별도 file 없이 응답에 grid 포함
      "radio_map_meta": {...},
      "local_artifacts": { "imageUrl": ..., "sionna_run_id": ..., "paths": {...} },
  }
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.db.session import SessionLocal
from app.models import Job, RfRun, SceneVersion, User
from app.models.rf_map import RfMap
from app.services import ai_api_client

logger = logging.getLogger(__name__)

JOB_TYPE_RF_SIMULATE = "rf_simulate"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"

RF_BACKEND_LOCAL = "local"


# ============================================================
# Submit
# ============================================================
async def submit_via_local_ai_api(
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
    """RfRun + Job 행 즉시 생성 (status=running) → 백그라운드 thread 가 ai_api 호출.

    submit 자체는 블로킹 없이 즉시 반환. UI 는 기존 SageMaker 폴링 흐름 그대로
    /rf-jobs/{job_id} 를 폴링하면 됨 (poll_rf_job 이 local backend 분기 처리).
    """
    if not access_points:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            "Local backend requires at least one access point.",
            400,
        )

    payload = _build_sionna_request_payload(
        scene_json=scene_json,
        floor_id=str(sv.floor_id),
        scene_version_id=str(sv.id),
        access_points=access_points,
        simulation=simulation,
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
            "backend": RF_BACKEND_LOCAL,
        },
        metrics_json={},
    )

    input_json: dict[str, Any] = {
        "rf_run_id": None,
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "requested_by": current_user.email,
        "backend": RF_BACKEND_LOCAL,
        "local": {
            "ai_api_payload_summary": {
                "walls": len(scene_json.get("walls") or []),
                "rooms": len(scene_json.get("rooms") or []),
                "primary_ap_id": access_points[0].get("id"),
            },
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
            f"Failed to persist RF simulation job (local backend): {exc}",
            500,
        ) from exc

    job_id = str(job.id)
    rf_run_id = str(rf_run.id)

    thread = threading.Thread(
        target=_background_run_ai_api,
        kwargs={"job_id": job_id, "rf_run_id": rf_run_id, "payload": payload},
        name=f"rf-local-{job_id[:8]}",
        daemon=True,
    )
    thread.start()

    logger.info(
        "RF job submitted (local ai_api) job_id=%s rf_run_id=%s thread=%s",
        job_id, rf_run_id, thread.name,
    )
    return rf_run, job


# ============================================================
# Background worker
# ============================================================
def _background_run_ai_api(
    *, job_id: str, rf_run_id: str, payload: dict[str, Any]
) -> None:
    """Thread entry point: ai_api 호출 + 결과 DB 영속화 (성공/실패 분기)."""
    try:
        response = ai_api_client.run_sionna_simulation(payload=payload)
    except ai_api_client.AiApiClientError as exc:
        logger.warning(
            "RF job %s: local ai_api call failed: %s", job_id, exc,
        )
        _persist_local_failure(job_id=job_id, rf_run_id=rf_run_id, message=str(exc))
        return
    except Exception as exc:  # pragma: no cover — 방어
        logger.exception("RF job %s: unexpected error during local ai_api call", job_id)
        _persist_local_failure(
            job_id=job_id, rf_run_id=rf_run_id,
            message=f"unexpected error: {exc}",
        )
        return

    status = str(response.get("status") or "").lower()
    if status != "succeeded":
        detail = response.get("detail") or response.get("error") or "ai_api returned non-success status"
        _persist_local_failure(
            job_id=job_id, rf_run_id=rf_run_id,
            message=f"ai_api status={status or 'unknown'}: {detail}",
        )
        return

    _persist_local_success(job_id=job_id, rf_run_id=rf_run_id, response=response)


def _persist_local_success(
    *, job_id: str, rf_run_id: str, response: dict[str, Any]
) -> None:
    """ai_api 성공 응답 → Job/RfRun/RfMap 업데이트. 새 DB 세션 사용."""
    db = SessionLocal()
    try:
        job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None:
            logger.warning("RF job %s missing on success persist", job_id)
            return
        if job.status != JOB_STATUS_RUNNING:
            logger.info(
                "RF job %s no longer running (status=%s), skipping persist",
                job_id, job.status,
            )
            return

        artifacts = response.get("artifacts") or {}
        metrics = response.get("metrics") or {}
        sionna_run_id = str(response.get("sionna_run_id") or "")
        image_url = response.get("imageUrl") or artifacts.get("imageUrl")

        radiomap = artifacts.get("radiomap") or {}
        radio_map_meta = {
            "grid_shape": radiomap.get("grid_shape"),
            "bounds_m": radiomap.get("bounds_m"),
            "cell_size_m": (artifacts.get("config") or {}).get("measurement_plane", {}).get("cell_size_m"),
            "rss_dbm": artifacts.get("rssi") or metrics.get("rssi_summary"),
            "coverage_summary": artifacts.get("coverage") or metrics.get("coverage_summary"),
            "valid_cell_count": artifacts.get("valid_cell_count") or metrics.get("valid_cell_count"),
            "valid_ratio": artifacts.get("valid_ratio") or metrics.get("valid_ratio"),
            # heatmap PNG 와 동일한 색 스케일 (vmin/vmax) — 프론트 ColorLegend 에서 사용.
            "color_scale": radiomap.get("color_scale"),
        }

        rf_run = db.execute(
            select(RfRun).where(RfRun.id == rf_run_id)
        ).scalar_one_or_none()
        if rf_run is not None:
            rf_run.status = JOB_STATUS_DONE
            rf_run.metrics_json = {
                "radio_map": radio_map_meta,
                "runtime": {
                    "mode": "local_ai_api",
                    "sionna_run_id": sionna_run_id,
                },
                "config": artifacts.get("config") or {},
            }
            _create_local_rf_maps(db, rf_run, image_url=image_url, radio_map_meta=radio_map_meta)

        job.status = JOB_STATUS_DONE
        job.result_json = {
            "rf_run_id": rf_run.id if rf_run is not None else None,
            "backend": RF_BACKEND_LOCAL,
            "heatmap_s3_uri": image_url,  # 같은 키 재사용 (http://... 값)
            "radio_map_s3_uri": None,
            "radio_map_meta": radio_map_meta,
            "local_artifacts": {
                "sionna_run_id": sionna_run_id,
                "imageUrl": image_url,
                "paths": {
                    k: artifacts.get(k)
                    for k in (
                        "visualization_path",
                        "valid_mask_path",
                        "geometry_overlay_path",
                        "geometry_debug_path",
                        "runtime_result_path",
                    )
                    if artifacts.get(k)
                },
            },
        }
        job.error_message = None
        job.finished_at = _now_utc()

        db.commit()
        logger.info(
            "RF job %s done (local ai_api) sionna_run_id=%s image_url=%s",
            job_id, sionna_run_id, image_url,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist local ai_api success for job %s: %s", job_id, exc)
    finally:
        db.close()


def _persist_local_failure(
    *, job_id: str, rf_run_id: str, message: str
) -> None:
    """ai_api 실패 → Job/RfRun status=failed. 새 DB 세션 사용."""
    db = SessionLocal()
    try:
        job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None:
            logger.warning("RF job %s missing on failure persist", job_id)
            return
        if job.status != JOB_STATUS_RUNNING:
            return

        job.status = JOB_STATUS_FAILED
        job.error_message = f"[local_ai_api] {message}"
        job.result_json = {
            "backend": RF_BACKEND_LOCAL,
            "error": {
                "backend_code": str(ErrorCode.INTERNAL_SERVER_ERROR),
                "container_code": None,
                "stage": "local_ai_api",
                "message": message,
                "retryable": True,
                "details": {},
            },
        }
        job.finished_at = _now_utc()

        rf_run = db.execute(
            select(RfRun).where(RfRun.id == rf_run_id)
        ).scalar_one_or_none()
        if rf_run is not None:
            rf_run.status = JOB_STATUS_FAILED

        db.commit()
        logger.warning("RF job %s failed (local ai_api): %s", job_id, message)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist local ai_api failure for job %s: %s", job_id, exc)
    finally:
        db.close()


def _create_local_rf_maps(
    db: Session, rf_run: RfRun, *, image_url: str | None, radio_map_meta: dict[str, Any]
) -> None:
    """heatmap RfMap row 1개 생성 (가능한 경우). SageMaker 경로의 _create_rf_map_rows 와 같은 의도."""
    if not image_url:
        return
    cell_size_m = radio_map_meta.get("cell_size_m") or 0.5
    try:
        resolution_cm = max(1, int(round(float(cell_size_m) * 100)))
    except (TypeError, ValueError):
        resolution_cm = 50
    metrics = {
        "rss_dbm": radio_map_meta.get("rss_dbm") or {},
        "coverage_summary": radio_map_meta.get("coverage_summary") or {},
        "valid_cell_count": radio_map_meta.get("valid_cell_count"),
        "valid_ratio": radio_map_meta.get("valid_ratio"),
        "grid_shape": radio_map_meta.get("grid_shape"),
        "color_scale": radio_map_meta.get("color_scale"),
    }
    db.add(
        RfMap(
            rf_run_id=rf_run.id,
            map_type="heatmap",
            resolution_cm=resolution_cm,
            storage_url=image_url,
            bounds_json=radio_map_meta.get("bounds_m") or {},
            metrics_json=metrics,
        )
    )


# ============================================================
# Payload builder: web-platform scene_json → ai_api SionnaRunRequestDto
# ============================================================
def _build_sionna_request_payload(
    *,
    scene_json: dict[str, Any],
    floor_id: str,
    scene_version_id: str,
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    """web-platform scene/simulation/AP 형식 → ai_api `/internal/sionna/run` body.

    Local backend 는 ai_api 가 single-AP 모델이므로 첫 번째 AP 만 사용한다.
    다중 AP 가 들어오면 첫 번째만 시뮬 (한계 — 추후 per-AP 반복 호출로 확장 가능).
    """
    walls = [
        {
            "id": f"w{i}",
            "start_xy": [float(w["x1"]), float(w["y1"])],
            "end_xy": [float(w["x2"]), float(w["y2"])],
            "height_m": float(w.get("height") or 2.6),
            "thickness_m": float(w.get("thickness") or 0.12),
            "material_id": str(w.get("material") or "plasterboard"),
        }
        for i, w in enumerate(scene_json.get("walls") or [])
    ]
    rooms = [
        {
            "id": f"r{i}",
            "polygon_xy": [[float(p[0]), float(p[1])] for p in (r.get("points") or [])],
        }
        for i, r in enumerate(scene_json.get("rooms") or [])
    ]

    primary_ap = access_points[0]
    ap_id = str(primary_ap.get("id") or "ap0")
    ap_position = [
        float(primary_ap.get("x_m") or primary_ap.get("x") or 0.0),
        float(primary_ap.get("y_m") or primary_ap.get("y") or 0.0),
        float(primary_ap.get("z_m") or primary_ap.get("z") or 1.2),
    ]

    frequency_hz = float(simulation.get("frequency_hz") or 5e9)
    frequency_ghz = frequency_hz / 1e9

    return {
        "engine": "sionna_rt",
        "floor_id": floor_id,
        "scene": {
            "scene_id": scene_version_id,
            "walls": walls,
            "rooms": rooms,
            "openings": [],
            "furniture": [],
        },
        "access_point": {
            "id": ap_id,
            "position_m": ap_position,
            "tx_power_dbm": float(simulation.get("tx_power_dbm")) if simulation.get("tx_power_dbm") is not None else None,
            "frequency_ghz": frequency_ghz,
        },
        "measurement_plane": {
            "z_m": float(simulation.get("measurement_plane_z_m") or 1.0),
            "cell_size_m": float(simulation.get("resolution_m") or 0.5),
        },
        "simulation": {
            "physical": {
                "frequency_ghz": frequency_ghz,
                "tx_power_dbm": float(simulation.get("tx_power_dbm") or 20.0),
            },
            "solver": {
                "max_depth": int(simulation.get("max_depth") or 3),
                "samples_per_tx": int(simulation.get("samples_per_tx") or 100_000),
                "seed": int(simulation.get("seed") or 42),
            },
        },
    }


# ============================================================
# Helpers
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

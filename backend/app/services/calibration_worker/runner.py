"""Calibration job 의 실제 알고리즘 오케스트레이터.

`job_poller._poll_single` 가 호출하는 `poll_calibration_job(db, job_id, current_user)` 의
새 구현. 흐름:

  1. Job + CalibrationRun + 필수 의존 row (SceneVersion / RfRun / MeasurementSession) 로드
  2. 측정 RSSI 점 수집 (rssi_dbm != None 만), AP 좌표 수집, 벽 segment 수집
  3. 8 차원 BO 로 path-loss objective 최소화 (~50 eval)
  4. best_params 를 metrics_json + ParameterUpdate row 들로 저장
  5. 옵션: CALIBRATION_AI_API_VERIFY=true 면 ai_api 1회 호출 → 결과도 metrics_json 에
  6. status=completed (실패 시 status=failed + error_message)

블로킹 CPU 작업 (BO 50회) 은 `run_in_threadpool` 로 thread 로 보내서 이벤트 루프
안 막음.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ap_layout import ApLayout
from app.models.calibration_run import CalibrationRun
from app.models.job import Job
from app.models.measurement_point import MeasurementPoint
from app.models.parameter_update import ParameterUpdate
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.services import ai_api_client
from app.services.calibration_worker import bo_optimizer
from app.services.calibration_worker.path_loss import (
    CALIBRATABLE_MATERIALS,
    AccessPoint,
    CalibrationParams,
    Measurement,
    WallSegment,
    compute_error_metrics,
)
from app.services.scene_version_export import export_scene_version_to_scene_json
from app.core.geom import wkb_to_geojson


logger = logging.getLogger(__name__)

JOB_TYPE_CALIBRATION = "calibration"


# ────────────────────────────────────────────────────────────────────
# BO 변수 공간 — 순서 = (5개 material scale, tx_offset, floor_th, furn_th)
# ────────────────────────────────────────────────────────────────────
_BO_BOUNDS: list[tuple[float, float]] = (
    [(0.3, 3.0)] * len(CALIBRATABLE_MATERIALS)  # 5 dims
    + [(-10.0, 10.0)]   # tx_power_offset_db
    + [(0.02, 0.20)]    # floor_thickness_m
    + [(0.02, 0.30)]    # furniture_default_thickness_m
)
_PARAM_NAMES: list[str] = (
    [f"materials.{m}.attenuation_scale" for m in CALIBRATABLE_MATERIALS]
    + ["physical.tx_power_offset_db",
       "scene_defaults.floor_thickness_m",
       "scene_defaults.furniture_default_thickness_m"]
)

# 기본 evaluation budget (env override 가능)
_BO_N_INITIAL = int(os.getenv("CALIBRATION_BO_N_INITIAL", "12"))
_BO_N_ITER = int(os.getenv("CALIBRATION_BO_N_ITER", "38"))


def _vector_to_params(x: np.ndarray) -> CalibrationParams:
    n_mat = len(CALIBRATABLE_MATERIALS)
    scales = {m: float(x[i]) for i, m in enumerate(CALIBRATABLE_MATERIALS)}
    return CalibrationParams(
        tx_power_offset_db=float(x[n_mat]),
        floor_thickness_m=float(x[n_mat + 1]),
        furniture_default_thickness_m=float(x[n_mat + 2]),
        material_attenuation_scales=scales,
    )


def _params_to_correction_profile(params: CalibrationParams) -> dict[str, Any]:
    """ai_api 가 받는 CorrectionProfile JSON 으로 직렬화.

    contract (친구 ai_api): materials.{label} 에 attenuation_scale 만 넣는 단순 형태.
    """
    return {
        "materials": {
            m: {"id": m, "attenuation_scale": params.scale_for(m)}
            for m in CALIBRATABLE_MATERIALS
        },
        "physical": {"tx_power_offset_db": params.tx_power_offset_db},
        "scene_defaults": {
            "floor_thickness_m": params.floor_thickness_m,
            "furniture_default_thickness_m": params.furniture_default_thickness_m,
        },
    }


# ────────────────────────────────────────────────────────────────────
# DB 로드
# ────────────────────────────────────────────────────────────────────
def _load_measurements(db: Session, session_id: str) -> list[Measurement]:
    rows = db.execute(
        select(MeasurementPoint).where(MeasurementPoint.session_id == session_id)
    ).scalars().all()
    out: list[Measurement] = []
    for p in rows:
        if p.rssi_dbm is None:
            continue
        gj = wkb_to_geojson(p.point_geom)
        if not gj or gj.get("type") != "Point":
            continue
        coords = gj.get("coordinates") or []
        if len(coords) < 2:
            continue
        out.append(Measurement(x=float(coords[0]), y=float(coords[1]),
                               rssi_dbm=float(p.rssi_dbm)))
    return out


def _load_aps(
    db: Session, rf_run_id: str, fallback_request_json: dict[str, Any] | None
) -> list[AccessPoint]:
    """우선 ApLayout 테이블, 비어 있으면 RfRun.request_json.access_points 사용."""
    layouts = db.execute(
        select(ApLayout).where(ApLayout.rf_run_id == rf_run_id)
    ).scalars().all()

    aps: list[AccessPoint] = []
    if layouts:
        for layout in layouts:
            gj = wkb_to_geojson(layout.point_geom)
            if not gj or gj.get("type") != "Point":
                continue
            coords = gj.get("coordinates") or []
            if len(coords) < 2:
                continue
            aps.append(AccessPoint(
                name=layout.ap_name,
                x=float(coords[0]),
                y=float(coords[1]),
                tx_power_dbm=float(layout.power_dbm) if layout.power_dbm is not None else 20.0,
            ))
        return aps

    if fallback_request_json:
        for entry in fallback_request_json.get("access_points") or []:
            pos = entry.get("position") or entry
            x = pos.get("x") if isinstance(pos, dict) else None
            y = pos.get("y") if isinstance(pos, dict) else None
            if x is None or y is None:
                continue
            aps.append(AccessPoint(
                name=str(entry.get("name") or entry.get("id") or "ap"),
                x=float(x),
                y=float(y),
                tx_power_dbm=float(entry.get("power_dbm") or entry.get("tx_power_dbm") or 20.0),
            ))
    return aps


def _load_walls(db: Session, scene_version_id: str) -> list[WallSegment]:
    """SceneVersion 의 wall centerline → WallSegment list.

    `scene_version_export` 의 헬퍼 재사용 대신 직접 변환 — endpoint export 가
    Sionna enum 으로 강제 매핑하기 때문에 원본 material_label 이 손실됨.
    """
    from app.models import Wall  # 순환 import 회피

    rows = db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all()

    out: list[WallSegment] = []
    for w in rows:
        gj = wkb_to_geojson(w.centerline_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        coords = gj.get("coordinates") or []
        if len(coords) < 2:
            continue
        x1, y1 = float(coords[0][0]), float(coords[0][1])
        x2, y2 = float(coords[-1][0]), float(coords[-1][1])
        out.append(WallSegment(
            x1=x1, y1=y1, x2=x2, y2=y2,
            thickness_m=float(w.thickness_m) if w.thickness_m is not None else 0.12,
            material=(w.material_label or "").lower() or None,
        ))
    return out


# ────────────────────────────────────────────────────────────────────
# 메인 진입점 (job_poller 가 호출하는 시그니처)
# ────────────────────────────────────────────────────────────────────
async def poll_calibration_job(
    db: Session, *, job_id: str, current_user: User
) -> Job | None:
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if job is None:
        logger.warning("Calibration job %s not found", job_id)
        return None
    if job.status != "running":
        return job

    calibration_run_id = (job.input_json or {}).get("calibration_run_id")
    if not calibration_run_id:
        _finalize_failure(db, None, job, "Job.input_json.calibration_run_id missing")
        return job

    cr = db.execute(
        select(CalibrationRun).where(CalibrationRun.id == calibration_run_id)
    ).scalar_one_or_none()
    if cr is None:
        _finalize_failure(db, None, job, "CalibrationRun not found")
        return job

    try:
        await _run_pipeline(db, cr, job)
    except Exception as exc:
        logger.exception("Calibration %s failed", cr.id)
        _finalize_failure(db, cr, job, f"unexpected error: {exc}")
    return job


async def _run_pipeline(db: Session, cr: CalibrationRun, job: Job) -> None:
    # 1) 입력 로드
    measurements = _load_measurements(db, cr.measurement_session_id)
    if not measurements:
        _finalize_failure(db, cr, job, "No measurement points with RSSI found.")
        return

    rf_run = db.execute(
        select(RfRun).where(RfRun.id == cr.rf_run_id)
    ).scalar_one_or_none()
    if rf_run is None:
        _finalize_failure(db, cr, job, "RfRun not found for calibration.")
        return

    aps = _load_aps(db, cr.rf_run_id, rf_run.request_json or {})
    if not aps:
        _finalize_failure(db, cr, job, "No access points (ApLayout or RfRun.request_json) found.")
        return

    walls = _load_walls(db, cr.scene_version_id)
    logger.info(
        "Calibration %s: measurements=%d aps=%d walls=%d → BO start (init=%d, iter=%d)",
        cr.id, len(measurements), len(aps), len(walls), _BO_N_INITIAL, _BO_N_ITER,
    )

    # 2) BO objective (블로킹) → thread 로
    def _objective(x: np.ndarray) -> float:
        params = _vector_to_params(x)
        m = compute_error_metrics(aps, walls, measurements, params)
        return m.rmse_dbm

    bo_result = await run_in_threadpool(
        bo_optimizer.minimize,
        _objective,
        _BO_BOUNDS,
        n_initial=_BO_N_INITIAL,
        n_iter=_BO_N_ITER,
    )

    best_params = _vector_to_params(bo_result.best_x)
    best_metrics = compute_error_metrics(aps, walls, measurements, best_params)
    baseline_metrics = compute_error_metrics(
        aps, walls, measurements, CalibrationParams()  # 모든 scale=1, offset=0
    )

    metrics: dict[str, Any] = {
        "rmse_dbm": round(best_metrics.rmse_dbm, 3),
        "mae_dbm": round(best_metrics.mae_dbm, 3),
        "n_measurement_points": best_metrics.n_points,
        "n_walls": len(walls),
        "n_access_points": len(aps),
        "baseline_rmse_dbm": round(baseline_metrics.rmse_dbm, 3),
        "baseline_mae_dbm": round(baseline_metrics.mae_dbm, 3),
        "bo_n_initial": bo_result.n_initial,
        "bo_n_iter": bo_result.n_iter,
        "best_params": _params_to_dict(best_params),
    }

    # 3) ai_api closed-loop (옵션)
    if ai_api_client.is_closed_loop_verify_enabled():
        try:
            scene_json = export_scene_version_to_scene_json(db, cr.scene_version_id)
            access_points_payload = [
                {"name": ap.name, "position": {"x": ap.x, "y": ap.y},
                 "power_dbm": ap.tx_power_dbm}
                for ap in aps
            ]
            simulation_payload = (rf_run.request_json or {}).get("simulation") or {}
            ai_resp = await run_in_threadpool(
                ai_api_client.run_sionna_with_correction,
                scene_json=scene_json,
                correction_profile=_params_to_correction_profile(best_params),
                access_points=access_points_payload,
                simulation=simulation_payload,
            )
            metrics["ai_api_result"] = ai_resp
        except ai_api_client.AiApiClientError as exc:
            metrics["ai_api_error"] = str(exc)
            logger.warning("Calibration %s: ai_api closed-loop failed (continuing): %s",
                           cr.id, exc)

    # 4) ParameterUpdate row 들 — best params 각 항목별로 1줄
    _write_parameter_updates(db, cr, best_params)

    # 5) 마무리
    now = datetime.now(timezone.utc)
    cr.metrics_json = metrics
    cr.status = "completed"
    cr.finished_at = now
    job.status = "completed"
    job.finished_at = now

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "Calibration %s completed: rmse=%.2f→%.2f dB over %d measurements",
        cr.id, baseline_metrics.rmse_dbm, best_metrics.rmse_dbm, best_metrics.n_points,
    )


# ────────────────────────────────────────────────────────────────────
# 헬퍼
# ────────────────────────────────────────────────────────────────────
def _params_to_dict(p: CalibrationParams) -> dict[str, Any]:
    return {
        "tx_power_offset_db": round(p.tx_power_offset_db, 3),
        "floor_thickness_m": round(p.floor_thickness_m, 4),
        "furniture_default_thickness_m": round(p.furniture_default_thickness_m, 4),
        "material_attenuation_scales": {
            k: round(v, 3) for k, v in p.material_attenuation_scales.items()
        },
    }


def _write_parameter_updates(
    db: Session, cr: CalibrationRun, params: CalibrationParams
) -> None:
    """best_params 각 항목 → ParameterUpdate row 1개씩.

    target_type='scene_version', target_id=cr.scene_version_id 로 통일.
    old_value_json 은 baseline (1.0 / 0.0 / 기본 두께) 으로 채움 — 그래야 변경 폭 추적 가능.
    """
    baseline = CalibrationParams()
    rows: list[ParameterUpdate] = []

    for m in CALIBRATABLE_MATERIALS:
        rows.append(ParameterUpdate(
            calibration_run_id=cr.id,
            target_type="scene_version",
            target_id=cr.scene_version_id,
            parameter_name=f"materials.{m}.attenuation_scale",
            old_value_json={"value": baseline.scale_for(m)},
            new_value_json={"value": round(params.scale_for(m), 3)},
        ))
    rows.append(ParameterUpdate(
        calibration_run_id=cr.id,
        target_type="scene_version",
        target_id=cr.scene_version_id,
        parameter_name="physical.tx_power_offset_db",
        old_value_json={"value": baseline.tx_power_offset_db},
        new_value_json={"value": round(params.tx_power_offset_db, 3)},
    ))
    rows.append(ParameterUpdate(
        calibration_run_id=cr.id,
        target_type="scene_version",
        target_id=cr.scene_version_id,
        parameter_name="scene_defaults.floor_thickness_m",
        old_value_json={"value": baseline.floor_thickness_m},
        new_value_json={"value": round(params.floor_thickness_m, 4)},
    ))
    rows.append(ParameterUpdate(
        calibration_run_id=cr.id,
        target_type="scene_version",
        target_id=cr.scene_version_id,
        parameter_name="scene_defaults.furniture_default_thickness_m",
        old_value_json={"value": baseline.furniture_default_thickness_m},
        new_value_json={"value": round(params.furniture_default_thickness_m, 4)},
    ))
    for r in rows:
        db.add(r)


def _finalize_failure(
    db: Session, cr: CalibrationRun | None, job: Job, message: str
) -> None:
    now = datetime.now(timezone.utc)
    if cr is not None:
        cr.status = "failed"
        cr.error_message = message
        cr.finished_at = now
    job.status = "failed"
    job.error_message = message
    job.finished_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.warning("Calibration job %s failed: %s", job.id, message)

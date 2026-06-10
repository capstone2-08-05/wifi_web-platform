"""Apply calibration parameters to a Sionna RT RF input.

The calibration worker uses a fast surrogate path-loss model to estimate several
parameters. Not every surrogate parameter is a valid Sionna RT knob. For the
physical rerun we intentionally apply only parameters that map cleanly to the
Sionna input:

- material attenuation scale -> effective wall thickness scale
- tx_power_offset_db -> bounded simulation.tx_power_dbm adjustment

Surrogate-only parameters such as path_loss_exp, floor_thickness_m, and
furniture_default_thickness_m are kept in metrics for diagnosis, but are not
forced into the Sionna scene.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calibration_run import CalibrationRun
from app.models.floor import Floor
from app.models.scene_version import SceneVersion

logger = logging.getLogger(__name__)


MIN_SIONNA_TX_POWER_DBM = 10.0
MAX_SIONNA_TX_POWER_DBM = 23.0
MIN_SIONNA_WALL_SCALE = 0.7
MAX_SIONNA_WALL_SCALE = 2.0
DEFAULT_TX_POWER_DBM = 20.0


_CALIB_TO_SIONNA: dict[str, str] = {
    "drywall": "plasterboard",
    "concrete": "concrete",
    "wood": "wood",
    "glass": "glass",
    "metal": "metal",
}
_SIONNA_TO_CALIB: dict[str, str] = {v: k for k, v in _CALIB_TO_SIONNA.items()}


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _has_best_params(run: CalibrationRun | None) -> bool:
    return bool(run and (run.metrics_json or {}).get("best_params"))


def get_latest_affine_calibration(db: Session, floor_id: str) -> dict[str, float] | None:
    """Return latest affine RSSI transfer params (slope, intercept_db) for this floor.

    evaluate_calibration_run 이 생성한 CalibrationRun 에서 조회.
    metrics_json.evaluation.calibration.slope / intercept_db 가 있어야 함.
    """
    rows = db.execute(
        select(CalibrationRun)
        .where(
            CalibrationRun.floor_id == str(floor_id),
            CalibrationRun.status == "completed",
        )
        .order_by(CalibrationRun.created_at.desc())
        .limit(20)
    ).scalars().all()
    for row in rows:
        calib = (row.metrics_json or {}).get("evaluation", {}).get("calibration") or {}
        slope = calib.get("slope")
        intercept = calib.get("intercept_db")
        if slope is not None and intercept is not None:
            return {"slope": float(slope), "intercept_db": float(intercept)}
    return None


def apply_affine_to_values(
    values_dbm: list[list[float | None]],
    slope: float,
    intercept_db: float,
) -> list[list[float | None]]:
    """2D RSSI grid 에 affine 변환 적용: calibrated = slope * raw + intercept_db."""
    return [
        [
            slope * v + intercept_db if v is not None else None
            for v in row
        ]
        for row in values_dbm
    ]


def get_latest_calibration(db: Session, scene_version_id: str) -> CalibrationRun | None:
    """Return latest completed calibration for this scene, then same project/space type."""
    exact = db.execute(
        select(CalibrationRun)
        .where(
            CalibrationRun.scene_version_id == str(scene_version_id),
            CalibrationRun.status == "completed",
        )
        .order_by(CalibrationRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if _has_best_params(exact):
        return exact

    target = db.execute(
        select(SceneVersion, Floor)
        .join(Floor, SceneVersion.floor_id == Floor.id)
        .where(SceneVersion.id == str(scene_version_id))
    ).first()
    if target is None:
        return None
    sv, floor = target
    if not floor.space_type:
        return None

    candidates = db.execute(
        select(CalibrationRun)
        .join(Floor, CalibrationRun.floor_id == Floor.id)
        .where(
            CalibrationRun.project_id == sv.project_id,
            CalibrationRun.status == "completed",
            Floor.space_type == floor.space_type,
        )
        .order_by(CalibrationRun.created_at.desc())
        .limit(10)
    ).scalars().all()
    for candidate in candidates:
        if _has_best_params(candidate):
            return candidate
    return None


def apply_to_scene_and_sim(
    scene_json: dict[str, Any],
    simulation: dict[str, Any],
    best_params: dict[str, Any],
) -> dict[str, Any]:
    """Mutate scene_json/simulation with bounded physical calibration values."""
    raw_scales: dict[str, float] = {
        str(k): float(v)
        for k, v in (best_params.get("material_attenuation_scales") or {}).items()
        if v is not None
    }
    tx_offset_raw = float(best_params.get("tx_power_offset_db") or 0.0)

    walls = scene_json.get("walls") or []
    scaled_count = 0
    applied_scales: dict[str, float] = {}
    for wall in walls:
        sionna_mat = str(wall.get("material") or "").lower()
        calib_key = _SIONNA_TO_CALIB.get(sionna_mat, sionna_mat)
        if calib_key not in raw_scales:
            continue
        raw_scale = raw_scales[calib_key]
        scale = _clamp(raw_scale, MIN_SIONNA_WALL_SCALE, MAX_SIONNA_WALL_SCALE)
        wall["thickness"] = float(wall.get("thickness") or 0.12) * scale
        applied_scales[calib_key] = scale
        scaled_count += 1

    base_tx_power = float(simulation.get("tx_power_dbm") or DEFAULT_TX_POWER_DBM)
    requested_tx_power = base_tx_power + tx_offset_raw
    calibrated_tx_power = _clamp(
        requested_tx_power,
        MIN_SIONNA_TX_POWER_DBM,
        MAX_SIONNA_TX_POWER_DBM,
    )
    simulation["tx_power_dbm"] = calibrated_tx_power

    summary = {
        "application_mode": "bounded_physical_sionna_rerun",
        "walls_scaled": scaled_count,
        "tx_power_dbm_before": round(base_tx_power, 4),
        "tx_power_offset_db_requested": round(tx_offset_raw, 4),
        "tx_power_dbm_requested": round(requested_tx_power, 4),
        "tx_power_offset_db_applied": round(calibrated_tx_power - base_tx_power, 4),
        "tx_power_dbm_after": round(calibrated_tx_power, 4),
        "tx_power_dbm_bounds": {
            "min": MIN_SIONNA_TX_POWER_DBM,
            "max": MAX_SIONNA_TX_POWER_DBM,
        },
        "material_scales_requested": raw_scales,
        "material_scales_applied": applied_scales,
        "wall_scale_bounds": {
            "min": MIN_SIONNA_WALL_SCALE,
            "max": MAX_SIONNA_WALL_SCALE,
        },
        "not_applied_to_sionna": {
            "path_loss_exp": best_params.get("path_loss_exp"),
            "floor_thickness_m": best_params.get("floor_thickness_m"),
            "furniture_default_thickness_m": best_params.get("furniture_default_thickness_m"),
        },
    }
    logger.info(
        "bounded physical calibration applied: walls=%d tx=%.2f->%.2f dBm",
        scaled_count,
        base_tx_power,
        calibrated_tx_power,
    )
    return summary

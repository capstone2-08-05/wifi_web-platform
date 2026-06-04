"""§11 Calibration: 실행 / 조회 / 파라미터 변경 이력 / 시스템 갱신"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import random
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.calibration_run import CalibrationRun
from app.models.job import Job
from app.models.measurement_session import MeasurementSession
from app.models.measurement_point import MeasurementPoint
from app.models.parameter_update import ParameterUpdate
from app.models.project import Project
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.rf.calibration_run import (
    CalibrationEvaluationRequest,
    CalibrationEvaluationResponse,
    CalibrationRunCreate,
    CalibrationRunResponse,
    CalibrationRunUpdate,
    ParameterUpdateCreate,
    ParameterUpdateResponse,
)
from app.core.geom import wkb_to_geojson


JOB_TYPE_CALIBRATION = "calibration"
ALLOWED_CALIBRATION_STATUS = {"queued", "running", "completed", "failed"}
# MVP defaults for the local residual layer. Keep these in one place so the
# map computation and response metadata cannot drift.
RESIDUAL_IDW_RADIUS_M = 6.0
RESIDUAL_IDW_WEIGHT = 0.6


# ---------------------------------------------------------------------------
# 권한 + 검증
# ---------------------------------------------------------------------------
def _get_owned_scene_version(
    db: Session, version_id: UUID, user: User
) -> SceneVersion:
    sv = db.execute(
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(version_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            status_code=404,
        )
    return sv


def _get_owned_rf_run(db: Session, rf_run_id: UUID, user: User) -> RfRun:
    rr = db.execute(
        select(RfRun)
        .join(Project, RfRun.project_id == Project.id)
        .where(
            RfRun.id == str(rf_run_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if rr is None:
        raise AppError(
            ErrorCode.RF_RUN_NOT_FOUND,
            "RF run not found.",
            status_code=404,
        )
    return rr


def _get_owned_session(
    db: Session, session_id: UUID, user: User
) -> MeasurementSession:
    s = db.execute(
        select(MeasurementSession)
        .join(Project, MeasurementSession.project_id == Project.id)
        .where(
            MeasurementSession.id == str(session_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if s is None:
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_NOT_FOUND,
            "Measurement session not found.",
            status_code=404,
        )
    return s


def _get_owned_sessions(
    db: Session, session_ids: list[UUID], user: User
) -> list[MeasurementSession]:
    sessions: list[MeasurementSession] = []
    for session_id in session_ids:
        sessions.append(_get_owned_session(db, session_id, user))
    return sessions


def _get_owned_calibration_run(
    db: Session, run_id: UUID, user: User
) -> CalibrationRun:
    cr = db.execute(
        select(CalibrationRun)
        .join(Project, CalibrationRun.project_id == Project.id)
        .where(
            CalibrationRun.id == str(run_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if cr is None:
        raise AppError(
            ErrorCode.CALIBRATION_RUN_NOT_FOUND,
            "Calibration run not found.",
            status_code=404,
        )
    return cr


def _get_calibration_run_or_404(db: Session, run_id: UUID) -> CalibrationRun:
    """[시스템 호출용] owner 체크 없이 단순 조회."""
    cr = db.execute(
        select(CalibrationRun).where(CalibrationRun.id == str(run_id))
    ).scalar_one_or_none()
    if cr is None:
        raise AppError(
            ErrorCode.CALIBRATION_RUN_NOT_FOUND,
            "Calibration run not found.",
            status_code=404,
        )
    return cr


# ---------------------------------------------------------------------------
# alias 매핑 (모델 → 명세 응답)
# ---------------------------------------------------------------------------
def _to_response(cr: CalibrationRun) -> CalibrationRunResponse:
    metrics = cr.metrics_json or {}
    # error_heatmap_url 은 명세상 top-level. 모델엔 별도 컬럼이 없어 metrics_json 안에 담는 규약.
    heatmap_url = metrics.get("error_heatmap_url")
    return CalibrationRunResponse(
        id=cr.id,
        status=cr.status,
        session_id=cr.measurement_session_id,
        rf_run_id=cr.rf_run_id,
        version_id=cr.scene_version_id,
        error_metrics_json=metrics,
        error_heatmap_url=heatmap_url,
        created_at=cr.created_at,
        finished_at=cr.finished_at,
    )


def _pu_to_response(pu: ParameterUpdate) -> ParameterUpdateResponse:
    return ParameterUpdateResponse(
        id=pu.id,
        calibration_run_id=pu.calibration_run_id,
        target_type=pu.target_type,
        target_id=pu.target_id,
        param_name=pu.parameter_name,
        old_value_json=pu.old_value_json,
        new_value_json=pu.new_value_json,
        created_at=pu.created_at,
    )


# ---------------------------------------------------------------------------
# §11.1 실행
# ---------------------------------------------------------------------------
def create_calibration_run(
    db: Session, payload: CalibrationRunCreate, user: User
) -> CalibrationRunResponse:
    sv = _get_owned_scene_version(db, payload.version_id, user)
    rr = _get_owned_rf_run(db, payload.rf_run_id, user)
    ms = _get_owned_session(db, payload.session_id, user)

    # 동일 floor 에 속해야 의미있는 비교. 다르면 거부.
    if not (sv.floor_id == rr.floor_id == ms.floor_id):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "scene_version / rf_run / measurement_session must belong to the same floor.",
            status_code=400,
        )

    cr = CalibrationRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        rf_run_id=rr.id,
        measurement_session_id=ms.id,
        status="queued",
    )
    db.add(cr)
    db.flush()

    # 백그라운드 워커 (job_poller) 가 픽업하도록 running 으로 시작.
    # poller 는 status=running 만 본다.
    now = datetime.now(timezone.utc)
    # space_type 결정 우선순위:
    #  1. payload.space_type (request override — 일회성)
    #  2. floor.space_type (사용자가 설정한 공간 유형 — source of truth)
    #  3. None → runner 가 "unknown" 으로 fallback
    from app.models.floor import Floor
    floor = db.execute(select(Floor).where(Floor.id == sv.floor_id)).scalar_one_or_none()
    effective_space_type = (
        payload.space_type
        or (floor.space_type if floor and floor.space_type else None)
    )
    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type=JOB_TYPE_CALIBRATION,
        status="running",
        input_json={
            "calibration_run_id": cr.id,
            "scene_version_id": sv.id,
            "rf_run_id": rr.id,
            "measurement_session_id": ms.id,
            "space_type": effective_space_type,
        },
        started_at=now,
    )
    db.add(job)

    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise
    return _to_response(cr)


@dataclass(frozen=True)
class _RadioMap:
    values: list[list[float]]
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def height(self) -> int:
        return len(self.values)

    @property
    def width(self) -> int:
        return len(self.values[0]) if self.values else 0


@dataclass(frozen=True)
class _EvalPoint:
    point_id: str
    session_id: str
    x_m: float
    y_m: float
    measured_rssi_dbm: float
    purpose: str
    split: str
    frequency_mhz: int | None = None
    baseline_pred_dbm: float | None = None
    calibrated_pred_dbm: float | None = None
    invalid_reason: str | None = None


def _load_radio_map(rf_run: RfRun) -> _RadioMap:
    radio_map = (rf_run.metrics_json or {}).get("radio_map") or {}
    values_raw = radio_map.get("values_dbm")
    bounds = radio_map.get("bounds_m") or {}
    if not isinstance(values_raw, list) or not values_raw:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "RF run does not contain radio_map.values_dbm.",
            status_code=400,
        )

    values: list[list[float]] = []
    width: int | None = None
    for row in values_raw:
        if not isinstance(row, list) or not row:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                "radio_map.values_dbm must be a non-empty 2D array.",
                status_code=400,
            )
        parsed = [float(v) for v in row]
        width = len(parsed) if width is None else width
        if len(parsed) != width:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                "radio_map.values_dbm rows must have the same width.",
                status_code=400,
            )
        values.append(parsed)

    min_x = float(bounds.get("min_x", 0.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_x = float(bounds.get("max_x", float(width or 0)))
    max_y = float(bounds.get("max_y", float(len(values))))
    if max_x <= min_x or max_y <= min_y:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "radio_map.bounds_m is missing or invalid.",
            status_code=400,
        )
    return _RadioMap(values=values, min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _sample_radio_map(radio_map: _RadioMap, x_m: float, y_m: float) -> tuple[float | None, str | None]:
    if x_m < radio_map.min_x or x_m > radio_map.max_x or y_m < radio_map.min_y or y_m > radio_map.max_y:
        return None, "outside_bounds"
    col = int(math.floor((x_m - radio_map.min_x) / (radio_map.max_x - radio_map.min_x) * radio_map.width))
    row = int(math.floor((y_m - radio_map.min_y) / (radio_map.max_y - radio_map.min_y) * radio_map.height))
    col = min(max(col, 0), radio_map.width - 1)
    row = min(max(row, 0), radio_map.height - 1)
    value = float(radio_map.values[row][col])
    if not math.isfinite(value) or value <= -200.0:
        return None, "invalid_radio_cell"
    return value, None


def _point_coords(row: MeasurementPoint) -> tuple[float, float]:
    gj = wkb_to_geojson(row.point_geom)
    coords = (gj or {}).get("coordinates") or [0.0, 0.0]
    return float(coords[0]), float(coords[1])


def _effective_purpose(point: MeasurementPoint, session_by_id: dict[str, MeasurementSession]) -> str:
    value = point.measurement_purpose or session_by_id[point.session_id].measurement_purpose or "unknown"
    return value if value in {"calibration", "validation", "reference", "unknown"} else "unknown"


def _split_points(
    points: list[MeasurementPoint],
    session_by_id: dict[str, MeasurementSession],
    *,
    strategy: str,
    holdout_ratio: float,
    seed: int,
) -> tuple[list[_EvalPoint], dict[str, Any]]:
    rows: list[tuple[MeasurementPoint, str]] = [
        (p, _effective_purpose(p, session_by_id))
        for p in points
        if p.rssi_dbm is not None
    ]
    if len(rows) < 5:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            f"Need at least 5 measurement points with RSSI for evaluation (got {len(rows)}).",
            status_code=400,
        )

    has_explicit_split = strategy == "purpose_or_random" and any(
        purpose in {"calibration", "validation", "reference"} for _, purpose in rows
    )
    split_by_id: dict[str, str] = {}
    if has_explicit_split:
        for p, purpose in rows:
            if purpose in {"calibration", "validation", "reference"}:
                split_by_id[p.id] = purpose
            else:
                split_by_id[p.id] = "calibration"
    else:
        sorted_rows = sorted(rows, key=lambda item: (str(item[0].session_id), str(item[0].id)))
        rng = random.Random(seed)
        shuffled = sorted_rows[:]
        rng.shuffle(shuffled)
        n_validation = max(1, int(round(len(shuffled) * holdout_ratio)))
        n_validation = min(n_validation, len(shuffled) - 1)
        validation_ids = {p.id for p, _ in shuffled[:n_validation]}
        for p, _ in sorted_rows:
            split_by_id[p.id] = "validation" if p.id in validation_ids else "calibration"

    result: list[_EvalPoint] = []
    for p, purpose in rows:
        x_m, y_m = _point_coords(p)
        split = split_by_id[p.id]
        result.append(
            _EvalPoint(
                point_id=p.id,
                session_id=p.session_id,
                x_m=x_m,
                y_m=y_m,
                measured_rssi_dbm=float(p.rssi_dbm),
                purpose=purpose,
                split=split,
                frequency_mhz=p.frequency_mhz,
            )
        )

    calibration_count = sum(1 for p in result if p.split == "calibration")
    validation_count = sum(1 for p in result if p.split == "validation")
    reference_count = sum(1 for p in result if p.split == "reference")
    if calibration_count == 0:
        raise AppError(ErrorCode.INVALID_REQUEST_BODY, "No calibration points available.", 400)

    return result, {
        "strategy": strategy,
        "holdout_ratio": holdout_ratio,
        "seed": seed,
        "source": "purpose" if has_explicit_split else "random",
        "n_total_points": len(result),
        "n_calibration_points": calibration_count,
        "n_validation_points": validation_count,
        "n_reference_points": reference_count,
    }


def _with_predictions(points: list[_EvalPoint], radio_map: _RadioMap) -> list[_EvalPoint]:
    sampled: list[_EvalPoint] = []
    for p in points:
        pred, invalid_reason = _sample_radio_map(radio_map, p.x_m, p.y_m)
        sampled.append(
            _EvalPoint(
                **{
                    **p.__dict__,
                    "baseline_pred_dbm": pred,
                    "invalid_reason": invalid_reason,
                }
            )
        )
    return sampled


def _calc_metrics(points: list[_EvalPoint]) -> dict[str, float]:
    baseline_errors = [abs(p.baseline_pred_dbm - p.measured_rssi_dbm) for p in points if p.baseline_pred_dbm is not None]
    calibrated_errors = [abs(p.calibrated_pred_dbm - p.measured_rssi_dbm) for p in points if p.calibrated_pred_dbm is not None]
    baseline_signed = [p.baseline_pred_dbm - p.measured_rssi_dbm for p in points if p.baseline_pred_dbm is not None]
    calibrated_signed = [p.calibrated_pred_dbm - p.measured_rssi_dbm for p in points if p.calibrated_pred_dbm is not None]
    if not baseline_errors or not calibrated_errors:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "No valid evaluation/reference points remain after radio map sampling.",
            400,
        )

    def mean(vals: list[float]) -> float:
        return sum(vals) / len(vals)

    baseline_mae = mean(baseline_errors)
    calibrated_mae = mean(calibrated_errors)
    baseline_rmse = math.sqrt(mean([v * v for v in baseline_errors]))
    calibrated_rmse = math.sqrt(mean([v * v for v in calibrated_errors]))
    return {
        "baseline_mae_db": baseline_mae,
        "baseline_rmse_db": baseline_rmse,
        "baseline_bias_db": mean(baseline_signed),
        "calibrated_mae_db": calibrated_mae,
        "calibrated_rmse_db": calibrated_rmse,
        "calibrated_bias_db": mean(calibrated_signed),
        "mae_improvement_db": baseline_mae - calibrated_mae,
        "rmse_improvement_db": baseline_rmse - calibrated_rmse,
        "mae_improvement_ratio": (baseline_mae - calibrated_mae) / baseline_mae if baseline_mae else 0.0,
    }


def _evaluation_points_for_metrics(points: list[_EvalPoint]) -> tuple[list[_EvalPoint], str, list[str]]:
    """Pick comparison points without forcing a separate validation purpose.

    Priority:
    1. validation points, for backward compatibility with the old 3-way split.
    2. reference points, the new presentation-oriented measured reference data.
    3. calibration points, as a last-resort local demo fallback. This is not a
       leak-free holdout metric, so a warning is returned with the response.
    """
    valid = [p for p in points if p.baseline_pred_dbm is not None]
    validation = [p for p in valid if p.split == "validation"]
    if validation:
        return validation, "validation", []
    reference = [p for p in valid if p.split == "reference"]
    if reference:
        return reference, "reference", []
    calibration = [p for p in valid if p.split == "calibration"]
    return calibration, "calibration", [
        "No reference/evaluation points were available, so metrics were computed on calibration points. Use separate reference measurements for presentation."
    ]


def _fit_rssi_transfer(points: list[_EvalPoint]) -> dict[str, float]:
    pairs = [
        (float(p.baseline_pred_dbm), float(p.measured_rssi_dbm))
        for p in points
        if p.baseline_pred_dbm is not None
    ]
    if not pairs:
        return {"slope": 1.0, "intercept": 0.0, "mean_offset_db": 0.0}

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    mean_offset = mean_y - mean_x
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if len(pairs) < 2 or var_x < 1e-6:
        return {"slope": 1.0, "intercept": mean_offset, "mean_offset_db": mean_offset}

    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    raw_slope = cov_xy / var_x
    # Indoor phone RSSI often has a much smaller dynamic range than raw RF maps.
    # Keep the transfer monotonic and avoid amplifying the original contrast.
    slope = min(1.0, max(0.05, raw_slope))
    intercept = mean_y - slope * mean_x
    return {
        "slope": slope,
        "intercept": intercept,
        "mean_offset_db": mean_offset,
        "raw_slope": raw_slope,
    }


def _apply_rssi_transfer(value_dbm: float, transfer: dict[str, float]) -> float:
    return float(transfer["slope"]) * value_dbm + float(transfer["intercept"])


def _idw_residual_at(
    x: float,
    y: float,
    residual_points: list[tuple[float, float, float]],
    *,
    power: float = 2.0,
    radius_m: float | None = RESIDUAL_IDW_RADIUS_M,
) -> float:
    numerator = 0.0
    denominator = 0.0
    nearest_dist = math.inf
    for px, py, residual in residual_points:
        dist = math.hypot(x - px, y - py)
        nearest_dist = min(nearest_dist, dist)
        if dist < 1e-6:
            return residual
        if radius_m is not None and dist > radius_m:
            continue
        weight = 1.0 / (dist ** power)
        numerator += weight * residual
        denominator += weight
    if denominator <= 0:
        return 0.0
    residual = numerator / denominator
    if radius_m is None:
        return residual
    # Fade residual influence near the search-radius edge to avoid painting
    # unmeasured distant areas too aggressively.
    fade = max(0.0, min(1.0, 1.0 - nearest_dist / radius_m))
    return residual * fade


def _hybrid_calibrated_value(
    baseline_dbm: float,
    x: float,
    y: float,
    transfer: dict[str, float],
    residual_points: list[tuple[float, float, float]],
) -> float:
    transfer_value = _apply_rssi_transfer(baseline_dbm, transfer)
    residual = _idw_residual_at(x, y, residual_points)
    return transfer_value + RESIDUAL_IDW_WEIGHT * residual


def _calibrated_map(
    radio_map: _RadioMap,
    transfer: dict[str, float],
    residual_points: list[tuple[float, float, float]],
) -> list[list[float]]:
    values = radio_map.values
    height = radio_map.height
    width = radio_map.width
    return [
        [
            _hybrid_calibrated_value(
                float(v),
                radio_map.min_x if width == 1 else radio_map.min_x + (radio_map.max_x - radio_map.min_x) * col_idx / (width - 1),
                radio_map.min_y if height == 1 else radio_map.min_y + (radio_map.max_y - radio_map.min_y) * row_idx / (height - 1),
                transfer,
                residual_points,
            )
            if math.isfinite(float(v))
            else float(v)
            for col_idx, v in enumerate(row)
        ]
        for row_idx, row in enumerate(values)
    ]


def _measurement_frequency_summary(points: list[_EvalPoint]) -> dict[str, Any]:
    freqs = [int(p.frequency_mhz) for p in points if p.frequency_mhz is not None and p.frequency_mhz > 0]
    if not freqs:
        return {"available": False, "message": "No measurement frequency_mhz values were uploaded."}
    bands = {
        "2.4GHz": sum(1 for f in freqs if 2400 <= f < 2500),
        "5GHz": sum(1 for f in freqs if 4900 <= f < 5900),
        "6GHz": sum(1 for f in freqs if 5925 <= f < 7125),
        "other": sum(1 for f in freqs if not (2400 <= f < 2500 or 4900 <= f < 5900 or 5925 <= f < 7125)),
    }
    dominant_band = max(bands, key=lambda k: bands[k])
    avg_mhz = sum(freqs) / len(freqs)
    return {
        "available": True,
        "point_count": len(freqs),
        "avg_frequency_mhz": round(avg_mhz, 1),
        "dominant_band": dominant_band,
        "bands": bands,
    }


def _rf_physical_summary(rf_run: RfRun) -> dict[str, Any]:
    request_sim = (rf_run.request_json or {}).get("simulation") or {}
    radio_map = (rf_run.metrics_json or {}).get("radio_map") or {}
    physical = radio_map.get("physical") or radio_map.get("config", {}).get("physical") or {}
    frequency_hz = request_sim.get("frequency_hz")
    frequency_ghz = physical.get("frequency_ghz")
    if frequency_ghz is None and frequency_hz is not None:
        frequency_ghz = float(frequency_hz) / 1e9
    tx_power_dbm = physical.get("tx_power_dbm", request_sim.get("tx_power_dbm"))
    return {
        "frequency_ghz": float(frequency_ghz) if frequency_ghz is not None else None,
        "tx_power_dbm": float(tx_power_dbm) if tx_power_dbm is not None else None,
    }


def _idw_reference_map(radio_map: _RadioMap, points: list[_EvalPoint]) -> list[list[float]]:
    power = 2.0
    epsilon = 1e-6
    out: list[list[float]] = []
    for row_idx in range(radio_map.height):
        y = radio_map.min_y if radio_map.height == 1 else radio_map.min_y + (radio_map.max_y - radio_map.min_y) * row_idx / (radio_map.height - 1)
        row: list[float] = []
        for col_idx in range(radio_map.width):
            x = radio_map.min_x if radio_map.width == 1 else radio_map.min_x + (radio_map.max_x - radio_map.min_x) * col_idx / (radio_map.width - 1)
            numerator = 0.0
            denominator = 0.0
            exact: float | None = None
            for p in points:
                dist = math.hypot(x - p.x_m, y - p.y_m)
                if dist < epsilon:
                    exact = p.measured_rssi_dbm
                    break
                weight = 1.0 / (dist ** power)
                numerator += weight * p.measured_rssi_dbm
                denominator += weight
            row.append(exact if exact is not None else numerator / denominator)
        out.append(row)
    return out


def _point_payload(p: _EvalPoint) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "point_id": p.point_id,
        "session_id": p.session_id,
        "x_m": p.x_m,
        "y_m": p.y_m,
        "rssi_dbm": p.measured_rssi_dbm,
        "measurement_purpose": p.purpose,
        "split": p.split,
    }
    if p.frequency_mhz is not None:
        payload["frequency_mhz"] = p.frequency_mhz
    if p.baseline_pred_dbm is not None:
        payload["baseline_pred_dbm"] = p.baseline_pred_dbm
        payload["baseline_error_db"] = abs(p.baseline_pred_dbm - p.measured_rssi_dbm)
    if p.calibrated_pred_dbm is not None:
        payload["calibrated_pred_dbm"] = p.calibrated_pred_dbm
        payload["calibrated_error_db"] = abs(p.calibrated_pred_dbm - p.measured_rssi_dbm)
    if p.invalid_reason is not None:
        payload["invalid_reason"] = p.invalid_reason
    return payload


def evaluate_calibration_run(
    db: Session, payload: CalibrationEvaluationRequest, user: User
) -> CalibrationEvaluationResponse:
    sv = _get_owned_scene_version(db, payload.scene_version_id, user)
    rr = _get_owned_rf_run(db, payload.rf_run_id, user)
    sessions = _get_owned_sessions(db, payload.measurement_session_ids, user)

    if sv.floor_id != str(payload.floor_id) or rr.floor_id != str(payload.floor_id):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "floor_id, scene_version_id, and rf_run_id must refer to the same floor.",
            status_code=400,
        )
    for session in sessions:
        if session.floor_id != str(payload.floor_id):
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                "All measurement sessions must belong to the requested floor.",
                status_code=400,
            )

    radio_map = _load_radio_map(rr)
    session_ids = [str(s.id) for s in sessions]
    rows = (
        db.execute(
            select(MeasurementPoint).where(
                MeasurementPoint.session_id.in_(session_ids),
                MeasurementPoint.rssi_dbm.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    split_points, split_meta = _split_points(
        rows,
        {str(s.id): s for s in sessions},
        strategy=payload.split.strategy,
        holdout_ratio=payload.split.holdout_ratio,
        seed=payload.split.seed,
    )
    sampled = _with_predictions(split_points, radio_map)
    valid_calibration = [
        p for p in sampled if p.split == "calibration" and p.baseline_pred_dbm is not None
    ]
    valid_validation = [
        p for p in sampled if p.split == "validation" and p.baseline_pred_dbm is not None
    ]
    invalid_points = [p for p in sampled if p.invalid_reason is not None]
    if not valid_calibration:
        outside = sum(1 for p in invalid_points if p.invalid_reason == "outside_bounds")
        invalid_cell = sum(1 for p in invalid_points if p.invalid_reason == "invalid_radio_cell")
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            (
                "측정점이 시뮬레이션 영역 밖에 있어 보정할 수 없습니다. "
                f"(전체 {len(sampled)}점, 영역 밖 {outside}점, 무효 셀 {invalid_cell}점). "
                f"시뮬 영역: x={radio_map.min_x:.1f}~{radio_map.max_x:.1f}m, "
                f"y={radio_map.min_y:.1f}~{radio_map.max_y:.1f}m. "
                "모바일 앱에서 도면 벽 안쪽의 시작 위치를 지정한 뒤 다시 측정해주세요."
            ),
            400,
        )
    rssi_transfer = _fit_rssi_transfer(valid_calibration)
    residual_points = [
        (
            p.x_m,
            p.y_m,
            p.measured_rssi_dbm - _apply_rssi_transfer(float(p.baseline_pred_dbm), rssi_transfer),
        )
        for p in valid_calibration
        if p.baseline_pred_dbm is not None
    ]
    offset_db = float(rssi_transfer["mean_offset_db"])
    calibrated_points: list[_EvalPoint] = []
    for p in sampled:
        calibrated_pred = (
            _hybrid_calibrated_value(
                float(p.baseline_pred_dbm),
                p.x_m,
                p.y_m,
                rssi_transfer,
                residual_points,
            )
            if p.baseline_pred_dbm is not None
            else None
        )
        calibrated_points.append(
            _EvalPoint(
                **{
                    **p.__dict__,
                    "calibrated_pred_dbm": calibrated_pred,
                }
            )
        )

    validation_points = [
        p for p in calibrated_points if p.split == "validation" and p.baseline_pred_dbm is not None
    ]
    metric_points, metric_point_source, metric_warnings = _evaluation_points_for_metrics(calibrated_points)
    metrics = _calc_metrics(metric_points)
    rounded_metrics = {k: round(v, 4) for k, v in metrics.items()}

    reference_points = [p for p in calibrated_points if p.split == "reference"]
    if not reference_points:
        reference_points = [
            p for p in calibrated_points if p.split in {"calibration", "validation"}
        ]
    reference_points = [p for p in reference_points if p.invalid_reason is None]
    measured_reference: dict[str, Any] | None = None
    warnings: list[str] = [*metric_warnings]
    if payload.visualization.include_reference_map:
        if len(reference_points) < 3:
            warnings.append("Measured reference map skipped because fewer than 3 valid reference points are available.")
        else:
            measured_reference = {
                "label": "Measured Reference Map",
                "method": "idw",
                "values_dbm": _idw_reference_map(radio_map, reference_points),
                "metadata": {
                    "point_count": len(reference_points),
                    "is_interpolated_reference": True,
                    "not_absolute_ground_truth": True,
                },
            }

    maps: dict[str, Any] = {
        "baseline": {
            "label": "Baseline Simulation",
            "values_dbm": radio_map.values,
            "bounds_m": {
                "min_x": radio_map.min_x,
                "min_y": radio_map.min_y,
                "max_x": radio_map.max_x,
                "max_y": radio_map.max_y,
            },
        },
        "calibrated": {
            "label": "Calibrated Simulation (Transfer + Residual IDW)",
            "values_dbm": _calibrated_map(radio_map, rssi_transfer, residual_points),
            "bounds_m": {
                "min_x": radio_map.min_x,
                "min_y": radio_map.min_y,
                "max_x": radio_map.max_x,
                "max_y": radio_map.max_y,
            },
            "offset_db": offset_db,
            "metadata": {
                "method": "affine_rssi_transfer_plus_residual_idw",
                "slope": round(float(rssi_transfer["slope"]), 6),
                "intercept_db": round(float(rssi_transfer["intercept"]), 6),
                "mean_offset_db": round(offset_db, 6),
                "residual_method": "idw",
                "residual_weight": RESIDUAL_IDW_WEIGHT,
                "residual_radius_m": RESIDUAL_IDW_RADIUS_M,
                "residual_point_count": len(residual_points),
                "purpose": "First matches the simulated RSSI scale to phone measurements, then blends local residuals with IDW.",
            },
        },
    }
    if measured_reference is not None:
        measured_reference["bounds_m"] = maps["baseline"]["bounds_m"]
        maps["measured_reference"] = measured_reference

    split_meta = {
        **split_meta,
        "n_reference_points": len(reference_points),
        "n_metric_points": len(metric_points),
        "metric_point_source": metric_point_source,
        "n_invalid_points": len(invalid_points),
    }
    frequency_summary = _measurement_frequency_summary(calibrated_points)
    rf_physical = _rf_physical_summary(rr)
    if frequency_summary.get("available") and rf_physical.get("frequency_ghz") is not None:
        measured_band = str(frequency_summary.get("dominant_band"))
        rf_band = "2.4GHz" if 2.3 <= float(rf_physical["frequency_ghz"]) < 2.6 else (
            "5GHz" if 4.9 <= float(rf_physical["frequency_ghz"]) < 5.9 else (
                "6GHz" if 5.925 <= float(rf_physical["frequency_ghz"]) < 7.125 else "other"
            )
        )
        if measured_band != "other" and measured_band != rf_band:
            warnings.append(
                f"Measured Wi-Fi band is mostly {measured_band}, but RF simulation used {rf_physical['frequency_ghz']:.2f}GHz ({rf_band})."
            )
    evaluation = {
        "split": split_meta,
        "calibration": {
            "method": "affine_rssi_transfer_plus_residual_idw",
            "offset_db": round(offset_db, 4),
            "slope": round(float(rssi_transfer["slope"]), 4),
            "intercept_db": round(float(rssi_transfer["intercept"]), 4),
            "mean_offset_db": round(offset_db, 4),
            "residual_method": "idw",
            "residual_weight": RESIDUAL_IDW_WEIGHT,
            "residual_radius_m": RESIDUAL_IDW_RADIUS_M,
            "equivalent_tx_power_offset_db": round(offset_db, 4),
        },
        "rf_physical": rf_physical,
        "measurement_frequency": frequency_summary,
        "visualization": {
            "map_type": "three_way_comparison",
            "reference_map_method": payload.visualization.reference_map_method,
            "rssi_min_dbm": payload.visualization.rssi_min_dbm,
            "rssi_max_dbm": payload.visualization.rssi_max_dbm,
            "reference_map_is_visual_only": True,
            "metric_point_source": metric_point_source,
            "warnings": warnings,
        },
        "metrics": rounded_metrics,
    }

    response_payload = {
        "calibration_run_id": "",
        "status": "completed",
        "maps": maps,
        "color_scale": {
            "min_dbm": payload.visualization.rssi_min_dbm,
            "max_dbm": payload.visualization.rssi_max_dbm,
        },
        "points": {
            "calibration": [_point_payload(p) for p in calibrated_points if p.split == "calibration"],
            "validation": [_point_payload(p) for p in validation_points],
            "evaluation": [_point_payload(p) for p in metric_points],
            "reference": [_point_payload(p) for p in reference_points],
            "invalid": [_point_payload(p) for p in invalid_points],
        },
        "metrics": rounded_metrics,
        "evaluation": evaluation,
    }

    cr = CalibrationRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        rf_run_id=rr.id,
        measurement_session_id=session_ids[0],
        status="completed",
        finished_at=datetime.now(timezone.utc),
        metrics_json={
            **rounded_metrics,
            "evaluation": evaluation,
            "evaluation_response": response_payload,
        },
    )
    db.add(cr)
    db.flush()
    response_payload["calibration_run_id"] = cr.id
    cr.metrics_json = {
        **rounded_metrics,
        "evaluation": evaluation,
        "evaluation_response": response_payload,
    }
    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise

    return CalibrationEvaluationResponse(**response_payload)


# ---------------------------------------------------------------------------
# §11.2 결과 조회
# ---------------------------------------------------------------------------
def get_calibration_run(
    db: Session, run_id: UUID, user: User
) -> CalibrationRunResponse:
    return _to_response(_get_owned_calibration_run(db, run_id, user))


# ---------------------------------------------------------------------------
# §11.3 파라미터 변경 이력
# ---------------------------------------------------------------------------
def list_parameter_updates(
    db: Session, run_id: UUID, user: User
) -> list[ParameterUpdateResponse]:
    cr = _get_owned_calibration_run(db, run_id, user)
    rows = (
        db.execute(
            select(ParameterUpdate)
            .where(ParameterUpdate.calibration_run_id == cr.id)
            .order_by(ParameterUpdate.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [_pu_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# 시스템 호출 (AI 워커 → 백엔드)
# ---------------------------------------------------------------------------
def _find_associated_job(db: Session, calibration_run_id: str) -> Job | None:
    return db.execute(
        select(Job).where(
            Job.job_type == JOB_TYPE_CALIBRATION,
            Job.input_json["calibration_run_id"].astext == calibration_run_id,
        )
    ).scalar_one_or_none()


def update_calibration_run(
    db: Session, run_id: UUID, payload: CalibrationRunUpdate
) -> CalibrationRunResponse:
    cr = _get_calibration_run_or_404(db, run_id)
    data = payload.model_dump(exclude_unset=True)

    new_status = data.get("status")
    if new_status is not None and new_status not in ALLOWED_CALIBRATION_STATUS:
        raise AppError(
            ErrorCode.INVALID_CALIBRATION_STATUS,
            f"Invalid status: {new_status}. Allowed: {sorted(ALLOWED_CALIBRATION_STATUS)}",
            status_code=400,
        )

    now = datetime.now(timezone.utc)
    if new_status is not None:
        cr.status = new_status
        if new_status in {"completed", "failed"} and cr.finished_at is None:
            cr.finished_at = now
    if "metrics_json" in data and data["metrics_json"] is not None:
        cr.metrics_json = data["metrics_json"]
    if "error_message" in data:
        cr.error_message = data["error_message"]

    job = _find_associated_job(db, cr.id)
    if job is not None:
        if new_status is not None:
            job.status = new_status
            if new_status == "running" and job.started_at is None:
                job.started_at = now
            if new_status in {"completed", "failed"}:
                job.finished_at = now
        if "error_message" in data:
            job.error_message = data["error_message"]

    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise
    return _to_response(cr)


def create_parameter_update(
    db: Session, run_id: UUID, payload: ParameterUpdateCreate
) -> ParameterUpdateResponse:
    cr = _get_calibration_run_or_404(db, run_id)
    pu = ParameterUpdate(
        calibration_run_id=cr.id,
        target_type=payload.target_type,
        target_id=str(payload.target_id),
        parameter_name=payload.param_name,
        old_value_json=payload.old_value_json,
        new_value_json=payload.new_value_json,
    )
    db.add(pu)
    try:
        db.commit()
        db.refresh(pu)
    except Exception:
        db.rollback()
        raise
    return _pu_to_response(pu)

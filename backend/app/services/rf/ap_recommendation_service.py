"""Grid-based AP placement recommendation."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
from app.models.calibration_run import CalibrationRun
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.rf.ap_recommendation import (
    ApRecommendationBBox,
    ApRecommendationCalibrationInfo,
    ApRecommendationItem,
    ApRecommendationRequest,
    ApRecommendationResponse,
)
from app.services.rf.calibration_worker.path_loss import (
    AccessPoint,
    CalibrationParams,
    Measurement,
    WallSegment,
    predict_rssi_best_ap,
)
from app.services.rf.scene_obstacles import (
    column_wall_segments_for_objects,
    normalize_rf_material,
)

logger = logging.getLogger(__name__)

_EVAL_GRID_STEP_M = 1.0
_MIN_CANDIDATES = 4
_DEFAULT_COVERAGE_THRESHOLD_DBM = -67.0
_DEFAULT_WEAK_ZONE_THRESHOLD_DBM = -67.0

SCORE_WEIGHTS: dict[str, float] = {
    "coverage": 0.30,
    "weak_zone_improvement": 0.25,
    "bottom_10_percent": 0.20,
    "average_rssi": 0.15,
    "baseline_improvement": 0.10,
}


@dataclass
class WeightedEvalPoint:
    x: float
    y: float
    weight: float = 1.0
    zone_label: str | None = None
    baseline_rssi_dbm: float | None = None


@dataclass
class PredictedEvalPoint:
    x: float
    y: float
    weight: float
    zone_label: str | None
    baseline_rssi_dbm: float | None
    candidate_rssi_dbm: float


@dataclass
class RssiTransfer:
    slope: float = 1.0
    intercept_db: float = 0.0
    method: str = "identity"
    calibration_run_id: str | None = None
    residual_enabled: bool = False
    residual_weight: float = 0.0


@dataclass
class CandidateMetrics:
    coverage_score: float
    coverage_ratio: float
    weak_zone_improvement_score: float | None
    weak_zone_improvement_db: float | None
    bottom_10_percent_score: float
    bottom_10_percent_rssi_dbm: float
    average_rssi_score: float
    average_rssi_dbm: float
    baseline_improvement_score: float | None
    baseline_improvement_db: float | None
    final_score: float


def recommend_ap_location(
    db: Session,
    request: ApRecommendationRequest,
    current_user: User,
) -> ApRecommendationResponse:
    """Recommend Top-N AP coordinates using weighted RSSI quality metrics."""
    sv = db.execute(
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(request.scene_version_id),
            Project.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if sv is None:
        raise AppError(ErrorCode.SCENE_VERSION_NOT_FOUND, "Scene version not found.", 404)

    walls = _load_walls(db, str(sv.id))
    params = _load_calibration_params(db, str(sv.id), request.calibration_run_id)
    rssi_transfer = _load_rssi_transfer(db, str(sv.id), request.calibration_run_id)
    existing_aps = _parse_existing_aps(request.existing_aps)

    candidates = _generate_candidates_for_request(request)
    if not candidates:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "No AP candidates could be generated. Check candidate_bboxes and step_m.",
            400,
        )

    raw_eval_points = _generate_eval_points(db, str(sv.id))
    if not raw_eval_points:
        raw_eval_points = [
            Measurement(x=x, y=y, rssi_dbm=0.0)
            for x, y in _generate_eval_fallback_points(request)
        ]
    weighted_points = _build_weighted_eval_points(
        raw_eval_points,
        priority_zones=request.priority_zones,
        excluded_zones=request.excluded_zones,
    )
    if not weighted_points:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "All evaluation points were excluded. Adjust excluded_zones or floor geometry.",
            400,
        )

    _attach_baseline_rssi(
        points=weighted_points,
        existing_aps=existing_aps,
        walls=walls,
        params=params,
        transfer=rssi_transfer,
    )

    logger.info(
        "AP recommendation start: scene=%s candidates=%d eval=%d weighted=%d existing_aps=%d calibration=%s",
        sv.id,
        len(candidates),
        len(raw_eval_points),
        len(weighted_points),
        len(existing_aps),
        rssi_transfer.method,
    )

    top_results = _grid_search_topn(
        candidates=candidates,
        eval_points=weighted_points,
        existing_aps=existing_aps,
        walls=walls,
        params=params,
        transfer=rssi_transfer,
        recommendation_mode=request.recommendation_mode,
        coverage_threshold_dbm=request.coverage_threshold_dbm
        or _DEFAULT_COVERAGE_THRESHOLD_DBM,
        weak_zone_threshold_dbm=request.weak_zone_threshold_dbm
        or _DEFAULT_WEAK_ZONE_THRESHOLD_DBM,
        n=request.n_recommendations,
    )

    recommendations = [
        _to_response_item(i + 1, x, y, metrics)
        for i, (x, y, metrics) in enumerate(top_results)
    ]

    return ApRecommendationResponse(
        recommendations=recommendations,
        candidates_evaluated=len(candidates),
        eval_points_count=len(raw_eval_points),
        weighted_eval_points_count=len(weighted_points),
        calibration_applied=rssi_transfer.method != "identity",
        calibration=ApRecommendationCalibrationInfo(
            method=rssi_transfer.method,
            slope=round(rssi_transfer.slope, 6),
            intercept_db=round(rssi_transfer.intercept_db, 6),
            residual_used=False,
            calibration_run_id=UUID(rssi_transfer.calibration_run_id)
            if rssi_transfer.calibration_run_id
            else None,
        ),
        score_weights=SCORE_WEIGHTS,
    )


def _to_response_item(
    rank: int,
    x: float,
    y: float,
    metrics: CandidateMetrics,
) -> ApRecommendationItem:
    return ApRecommendationItem(
        rank=rank,
        recommended_x=round(x, 3),
        recommended_y=round(y, 3),
        score=round(metrics.final_score, 4),
        coverage_score=round(metrics.coverage_score, 4),
        coverage_ratio=round(metrics.coverage_ratio, 4),
        weak_zone_improvement_score=_round_optional(metrics.weak_zone_improvement_score),
        weak_zone_improvement_db=_round_optional(metrics.weak_zone_improvement_db),
        bottom_10_percent_score=round(metrics.bottom_10_percent_score, 4),
        bottom_10_percent_rssi_dbm=round(metrics.bottom_10_percent_rssi_dbm, 2),
        average_rssi_score=round(metrics.average_rssi_score, 4),
        average_rssi_dbm=round(metrics.average_rssi_dbm, 2),
        baseline_improvement_score=_round_optional(metrics.baseline_improvement_score),
        baseline_improvement_db=_round_optional(metrics.baseline_improvement_db),
    )


def _round_optional(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _generate_candidates(
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    step_m: float,
) -> list[tuple[float, float]]:
    if x_max <= x_min or y_max <= y_min:
        return []
    pts: list[tuple[float, float]] = []
    x = x_min
    while x <= x_max + 1e-9:
        y = y_min
        while y <= y_max + 1e-9:
            pts.append((x, y))
            y = round(y + step_m, 6)
        x = round(x + step_m, 6)
    return pts


def _generate_candidates_for_request(
    request: ApRecommendationRequest,
) -> list[tuple[float, float]]:
    boxes = _candidate_boxes_for_request(request)
    seen: set[tuple[float, float]] = set()
    candidates: list[tuple[float, float]] = []
    for box in boxes:
        for point in _generate_candidates(
            box.x_min,
            box.x_max,
            box.y_min,
            box.y_max,
            _candidate_step_for_box(box, request.step_m),
        ):
            key = (round(point[0], 6), round(point[1], 6))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(point)
    return candidates


def _candidate_boxes_for_request(
    request: ApRecommendationRequest,
) -> list[ApRecommendationBBox]:
    if request.candidate_bboxes:
        return request.candidate_bboxes
    if request.target_bboxes:
        out: list[ApRecommendationBBox] = []
        for raw in request.target_bboxes:
            try:
                out.append(
                    ApRecommendationBBox(
                        x_min=float(raw["x_min"]),
                        x_max=float(raw["x_max"]),
                        y_min=float(raw["y_min"]),
                        y_max=float(raw["y_max"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out
    if (
        request.x_min is not None
        and request.x_max is not None
        and request.y_min is not None
        and request.y_max is not None
    ):
        return [
            ApRecommendationBBox(
                x_min=request.x_min,
                x_max=request.x_max,
                y_min=request.y_min,
                y_max=request.y_max,
            )
        ]
    return []


def _candidate_step_for_box(box: ApRecommendationBBox, step_m: float) -> float:
    width = box.x_max - box.x_min
    height = box.y_max - box.y_min
    if width <= 0 or height <= 0:
        return step_m
    if (math.floor(width / step_m) + 1) * (math.floor(height / step_m) + 1) >= _MIN_CANDIDATES:
        return step_m
    return max(0.1, min(width, height) / 2.0)


def _generate_eval_fallback_points(
    request: ApRecommendationRequest,
) -> list[tuple[float, float]]:
    boxes = _candidate_boxes_for_request(request)
    if not boxes:
        return []
    points: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for box in boxes:
        for point in _generate_candidates(
            box.x_min,
            box.x_max,
            box.y_min,
            box.y_max,
            _EVAL_GRID_STEP_M,
        ):
            key = (round(point[0], 6), round(point[1], 6))
            if key in seen:
                continue
            seen.add(key)
            points.append(point)
    return points


def _generate_eval_points(
    db: Session,
    scene_version_id: str,
) -> list[Measurement]:
    from app.models.wall import Wall

    rows = db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all()
    if not rows:
        return []

    xs: list[float] = []
    ys: list[float] = []
    for w in rows:
        gj = wkb_to_geojson(w.centerline_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        for coord in (gj.get("coordinates") or []):
            try:
                xs.append(float(coord[0]))
                ys.append(float(coord[1]))
            except (TypeError, ValueError, IndexError):
                continue
    if not xs:
        return []

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    pts: list[Measurement] = []
    x = min_x
    while x <= max_x + 1e-9:
        y = min_y
        while y <= max_y + 1e-9:
            pts.append(Measurement(x=x, y=y, rssi_dbm=0.0))
            y = round(y + _EVAL_GRID_STEP_M, 6)
        x = round(x + _EVAL_GRID_STEP_M, 6)
    return pts


def _build_weighted_eval_points(
    eval_points: list[Measurement],
    *,
    priority_zones: list[Any],
    excluded_zones: list[Any],
) -> list[WeightedEvalPoint]:
    weighted: list[WeightedEvalPoint] = []
    for point in eval_points:
        if any(_point_in_bbox(point.x, point.y, zone) for zone in excluded_zones):
            continue
        weight = 1.0
        label: str | None = None
        for zone in priority_zones:
            if _point_in_bbox(point.x, point.y, zone):
                zone_weight = float(getattr(zone, "weight", 1.0))
                if zone_weight >= weight or label is None:
                    weight = zone_weight
                    label = getattr(zone, "label", None)
        if weight <= 0:
            continue
        weighted.append(
            WeightedEvalPoint(
                x=point.x,
                y=point.y,
                weight=weight,
                zone_label=label,
            )
        )
    return weighted


def _point_in_bbox(x: float, y: float, box: Any) -> bool:
    return (
        float(box.x_min) <= x <= float(box.x_max)
        and float(box.y_min) <= y <= float(box.y_max)
    )


def _load_walls(db: Session, scene_version_id: str) -> list[WallSegment]:
    from app.models.object import SceneObject
    from app.models.wall import Wall

    rows = db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all()
    objects = db.execute(
        select(SceneObject).where(SceneObject.scene_version_id == scene_version_id)
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
        out.append(
            WallSegment(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                thickness_m=float(w.thickness_m) if w.thickness_m is not None else 0.12,
                material=normalize_rf_material(w.material_label),
            )
        )
    for seg in column_wall_segments_for_objects(objects):
        out.append(
            WallSegment(
                x1=float(seg["x1"]),
                y1=float(seg["y1"]),
                x2=float(seg["x2"]),
                y2=float(seg["y2"]),
                thickness_m=float(seg["thickness_m"]),
                material=str(seg["material"]) if seg["material"] else None,
            )
        )
    return out


def _load_calibration_params(
    db: Session,
    scene_version_id: str,
    calibration_run_id=None,
) -> CalibrationParams:
    from app.services.rf.calibration_worker.apply import get_latest_calibration

    run = None
    if calibration_run_id is not None:
        run = _get_calibration_for_scene_or_400(db, scene_version_id, calibration_run_id)
    if run is None:
        run = get_latest_calibration(db, scene_version_id)
    if run is None or not run.metrics_json:
        return CalibrationParams()

    best = (run.metrics_json or {}).get("best_params") or {}
    if not best:
        return CalibrationParams()

    return CalibrationParams(
        tx_power_offset_db=_finite_float(best.get("tx_power_offset_db"), 0.0),
        path_loss_exp=_finite_float(best.get("path_loss_exp"), 3.0),
        floor_thickness_m=_finite_float(best.get("floor_thickness_m"), 0.10),
        furniture_default_thickness_m=_finite_float(
            best.get("furniture_default_thickness_m"),
            0.05,
        ),
        material_attenuation_scales={
            str(k): _finite_float(v, 1.0)
            for k, v in (best.get("material_attenuation_scales") or {}).items()
        },
    )


def _load_rssi_transfer(
    db: Session,
    scene_version_id: str,
    calibration_run_id=None,
) -> RssiTransfer:
    run = None
    if calibration_run_id is not None:
        run = _get_calibration_for_scene_or_400(db, scene_version_id, calibration_run_id)
    else:
        run = db.execute(
            select(CalibrationRun)
            .where(
                CalibrationRun.scene_version_id == str(scene_version_id),
                CalibrationRun.status == "completed",
            )
            .order_by(CalibrationRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if run is None or not run.metrics_json:
        return RssiTransfer()

    calibration = _find_calibration_metrics(run.metrics_json)
    if not calibration:
        return RssiTransfer()

    slope = _finite_float(calibration.get("slope"), 1.0)
    intercept = _finite_float(
        calibration.get("intercept_db", calibration.get("intercept")),
        0.0,
    )
    if not math.isfinite(slope) or not math.isfinite(intercept):
        return RssiTransfer()
    return RssiTransfer(
        slope=slope,
        intercept_db=intercept,
        method=str(calibration.get("method") or "affine_rssi_transfer"),
        calibration_run_id=str(run.id),
        residual_enabled=False,
        residual_weight=0.0,
    )


def _get_calibration_for_scene_or_400(
    db: Session,
    scene_version_id: str,
    calibration_run_id: Any,
) -> CalibrationRun | None:
    run = db.get(CalibrationRun, str(calibration_run_id))
    if run is None:
        raise AppError(ErrorCode.INVALID_REQUEST_BODY, "Calibration run not found.", 400)
    if str(run.scene_version_id) != str(scene_version_id):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "Calibration run does not belong to this scene_version_id.",
            400,
        )
    return run


def _find_calibration_metrics(metrics_json: dict[str, Any]) -> dict[str, Any] | None:
    evaluation = metrics_json.get("evaluation")
    if isinstance(evaluation, dict):
        calibration = evaluation.get("calibration")
        if isinstance(calibration, dict):
            return calibration
    maps = metrics_json.get("maps")
    if isinstance(maps, dict):
        calibrated = maps.get("calibrated")
        if isinstance(calibrated, dict):
            calibration = calibrated.get("calibration")
            if isinstance(calibration, dict):
                return calibration
    calibration = metrics_json.get("calibration")
    if isinstance(calibration, dict):
        return calibration
    return None


def _finite_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _parse_existing_aps(raw: list[dict]) -> list[AccessPoint]:
    aps: list[AccessPoint] = []
    for i, ap in enumerate(raw):
        x = ap.get("x_m") if ap.get("x_m") is not None else ap.get("x")
        y = ap.get("y_m") if ap.get("y_m") is not None else ap.get("y")
        if x is None or y is None:
            continue
        aps.append(
            AccessPoint(
                name=str(ap.get("id") or ap.get("name") or f"ap{i + 1}"),
                x=_finite_float(x, 0.0),
                y=_finite_float(y, 0.0),
                tx_power_dbm=_finite_float(
                    ap.get("tx_power_dbm", ap.get("power_dbm")),
                    20.0,
                ),
            )
        )
    return aps


def _attach_baseline_rssi(
    *,
    points: list[WeightedEvalPoint],
    existing_aps: list[AccessPoint],
    walls: list[WallSegment],
    params: CalibrationParams,
    transfer: RssiTransfer,
) -> None:
    if not existing_aps:
        return
    for point in points:
        raw = predict_rssi_best_ap(existing_aps, _as_measurement(point), walls, params)
        point.baseline_rssi_dbm = apply_rssi_transfer(raw, transfer)


def apply_rssi_transfer(raw_pred: float, transfer: RssiTransfer) -> float:
    return transfer.slope * raw_pred + transfer.intercept_db


def _as_measurement(point: WeightedEvalPoint) -> Measurement:
    return Measurement(x=point.x, y=point.y, rssi_dbm=0.0)


def _grid_search_topn(
    *,
    candidates: list[tuple[float, float]],
    eval_points: list[WeightedEvalPoint],
    existing_aps: list[AccessPoint],
    walls: list[WallSegment],
    params: CalibrationParams,
    transfer: RssiTransfer,
    recommendation_mode: str,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
    n: int,
) -> list[tuple[float, float, CandidateMetrics]]:
    scored: list[tuple[float, float, CandidateMetrics]] = []

    for cx, cy in candidates:
        test_ap = AccessPoint(name="candidate", x=cx, y=cy)
        eval_aps = (
            existing_aps + [test_ap]
            if recommendation_mode == "add"
            else [test_ap]
        )
        predicted: list[PredictedEvalPoint] = []
        for point in eval_points:
            raw = predict_rssi_best_ap(eval_aps, _as_measurement(point), walls, params)
            calibrated = apply_rssi_transfer(raw, transfer)
            predicted.append(
                PredictedEvalPoint(
                    x=point.x,
                    y=point.y,
                    weight=point.weight,
                    zone_label=point.zone_label,
                    baseline_rssi_dbm=point.baseline_rssi_dbm,
                    candidate_rssi_dbm=calibrated,
                )
            )
        metrics = compute_ap_recommendation_metrics(
            predicted,
            coverage_threshold_dbm=coverage_threshold_dbm,
            weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        )
        scored.append((cx, cy, metrics))

    scored.sort(
        key=lambda t: (
            t[2].final_score,
            t[2].coverage_score,
            t[2].bottom_10_percent_score,
            t[2].average_rssi_score,
        ),
        reverse=True,
    )
    return scored[:n]


def compute_ap_recommendation_metrics(
    points: list[PredictedEvalPoint],
    *,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
) -> CandidateMetrics:
    total_weight = sum(max(0.0, p.weight) for p in points)
    if total_weight <= 0:
        return CandidateMetrics(
            coverage_score=0.0,
            coverage_ratio=0.0,
            weak_zone_improvement_score=None,
            weak_zone_improvement_db=None,
            bottom_10_percent_score=0.0,
            bottom_10_percent_rssi_dbm=-110.0,
            average_rssi_score=0.0,
            average_rssi_dbm=-110.0,
            baseline_improvement_score=None,
            baseline_improvement_db=None,
            final_score=0.0,
        )

    coverage_ratio = (
        sum(p.weight for p in points if p.candidate_rssi_dbm >= coverage_threshold_dbm)
        / total_weight
    )
    average_rssi = _weighted_average(
        [(p.candidate_rssi_dbm, p.weight) for p in points],
        default=-110.0,
    )
    bottom_rssi = _weighted_bottom_percent_average(points, percent=0.10)

    baseline_points = [p for p in points if p.baseline_rssi_dbm is not None]
    weak_points = [
        p for p in baseline_points
        if p.baseline_rssi_dbm is not None
        and p.baseline_rssi_dbm < weak_zone_threshold_dbm
    ]
    weak_improvement_db = None
    weak_score = None
    if weak_points:
        weak_improvement_db = _weighted_average(
            [
                (p.candidate_rssi_dbm - float(p.baseline_rssi_dbm), p.weight)
                for p in weak_points
            ],
            default=0.0,
        )
        weak_score = normalize_improvement(weak_improvement_db, 0.0, 15.0)

    baseline_improvement_db = None
    baseline_score = None
    if baseline_points:
        baseline_improvement_db = _weighted_average(
            [
                (p.candidate_rssi_dbm - float(p.baseline_rssi_dbm), p.weight)
                for p in baseline_points
            ],
            default=0.0,
        )
        baseline_score = normalize_improvement(baseline_improvement_db, 0.0, 10.0)

    coverage_score = coverage_ratio
    bottom_score = normalize_rssi(bottom_rssi, -85.0, coverage_threshold_dbm)
    avg_score = normalize_rssi(average_rssi, -85.0, -45.0)
    metric_scores: dict[str, float | None] = {
        "coverage": coverage_score,
        "weak_zone_improvement": weak_score,
        "bottom_10_percent": bottom_score,
        "average_rssi": avg_score,
        "baseline_improvement": baseline_score,
    }
    final_score = _weighted_metric_score(metric_scores)

    return CandidateMetrics(
        coverage_score=coverage_score,
        coverage_ratio=coverage_ratio,
        weak_zone_improvement_score=weak_score,
        weak_zone_improvement_db=weak_improvement_db,
        bottom_10_percent_score=bottom_score,
        bottom_10_percent_rssi_dbm=bottom_rssi,
        average_rssi_score=avg_score,
        average_rssi_dbm=average_rssi,
        baseline_improvement_score=baseline_score,
        baseline_improvement_db=baseline_improvement_db,
        final_score=final_score,
    )


def _weighted_metric_score(metric_scores: dict[str, float | None]) -> float:
    numerator = 0.0
    denominator = 0.0
    for key, weight in SCORE_WEIGHTS.items():
        value = metric_scores.get(key)
        if value is None:
            continue
        numerator += weight * value
        denominator += weight
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _weighted_average(values: list[tuple[float, float]], default: float) -> float:
    denominator = sum(max(0.0, weight) for _, weight in values)
    if denominator <= 0:
        return default
    return sum(value * max(0.0, weight) for value, weight in values) / denominator


def _weighted_bottom_percent_average(
    points: list[PredictedEvalPoint],
    *,
    percent: float,
) -> float:
    total_weight = sum(max(0.0, p.weight) for p in points)
    if total_weight <= 0:
        return -110.0
    target_weight = max(total_weight * percent, 1e-9)
    remaining = target_weight
    numerator = 0.0
    denominator = 0.0
    for point in sorted(points, key=lambda p: p.candidate_rssi_dbm):
        if remaining <= 0:
            break
        take = min(max(0.0, point.weight), remaining)
        numerator += point.candidate_rssi_dbm * take
        denominator += take
        remaining -= take
    if denominator <= 0:
        return -110.0
    return numerator / denominator


def normalize_linear(value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        return 0.0
    return max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))


def normalize_rssi(
    rssi_dbm: float,
    min_dbm: float = -85.0,
    max_dbm: float = -45.0,
) -> float:
    return normalize_linear(rssi_dbm, min_dbm, max_dbm)


def normalize_improvement(
    improvement_db: float,
    min_db: float = 0.0,
    max_db: float = 15.0,
) -> float:
    return normalize_linear(improvement_db, min_db, max_db)

"""Grid-based AP placement recommendation."""
from __future__ import annotations

import logging
import math
from decimal import Decimal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

if TYPE_CHECKING:
    import numpy as np

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rf_defaults import DEFAULT_FREQUENCY_HZ, DEFAULT_TX_POWER_DBM
from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
from app.models.ap_recommendation_run import (
    ApRecommendationItem as ApRecommendationItemRow,
    ApRecommendationRun,
)
from app.models.calibration_run import CalibrationRun
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.rf.ap_recommendation import (
    ApRecommendationApPosition,
    ApRecommendationBBox,
    ApRecommendationCalibrationInfo,
    ApRecommendationItem,
    ApRecommendationPredictionPoint,
    ApRecommendationRequest,
    ApRecommendationResponse,
    ApRecommendationRunResponse,
)
from app.services.rf.calibration_worker.path_loss import (
    AccessPoint,
    CalibrationParams,
    Measurement,
    WallSegment,
    predict_rssi_best_ap,
)
from app.services.rf.ap_recommendation_modes import (
    RecommendationPlan,
    build_recommendation_plan,
    compute_final_aps,
    compute_relocation_moves,
)
from app.services.rf.band_quality import (
    CombinePolicy,
    combine_band_values,
    compute_band_quality_summary,
)
from app.services.rf.physical_ap_helpers import (
    build_band_metadata,
    normalize_physical_aps_from_request,
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
_DEFAULT_UNZONED_WEIGHT = 0.2
_MIN_RECOMMENDATION_SPACING_M = 2.0

CalibrationPolicy = Literal["transfer_only", "best_params_only", "combined"]

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
    transfer_applied: bool = False
    residual_enabled: bool = False
    residual_weight: float = 0.0
    # 공간 잔차 보정 그리드 (GP 보간 결과)
    residual_grid: "np.ndarray | None" = None
    residual_xs: "np.ndarray | None" = None
    residual_ys: "np.ndarray | None" = None


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
    score_breakdown: dict[str, Any] = field(default_factory=dict)


async def recommend_ap_location(
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
    selected_calibration_run = _select_calibration_run(
        db,
        str(sv.id),
        request.calibration_run_id,
    )
    params = _params_from_run(selected_calibration_run, request.calibration_policy)
    best_params_applied = _best_params_applied(
        selected_calibration_run,
        request.calibration_policy,
    )
    rssi_transfer = _transfer_from_run(selected_calibration_run, request.calibration_policy)

    # 실측 데이터가 있으면 spatial residual 보정 추가
    residual_metadata = {
        "residual_mode": request.residual_mode,
        "residual_used": False,
        "residual_weight": 0.0,
    }
    if request.residual_mode != "none":
        residual_weight = (
            request.weak_residual_weight
            if request.residual_mode == "weak"
            else 1.0
        )
        rssi_transfer = _compute_residual_transfer(
            db,
            floor_id=str(sv.floor_id),
            scene_version_id=str(sv.id),
            transfer=rssi_transfer,
            residual_weight=residual_weight,
        )
        residual_metadata = {
            "residual_mode": request.residual_mode,
            "residual_used": rssi_transfer.residual_enabled,
            "residual_weight": rssi_transfer.residual_weight,
            "residual_note": (
                "Residual was applied weakly because residuals are measured from the previous AP layout."
                if request.residual_mode == "weak" and rssi_transfer.residual_enabled
                else ""
            ),
        }

    # Physical AP 정규화 — physical_aps 우선, 없으면 legacy existing_aps 변환
    _physical_aps = normalize_physical_aps_from_request(
        physical_aps=request.physical_aps or None,
        existing_aps=request.existing_aps,
        candidate_tx_power_dbm=request.candidate_tx_power_dbm,
    )
    existing_aps = _physical_aps_to_access_points(
        _physical_aps, request.candidate_tx_power_dbm
    )
    _validate_mode_targets(request, existing_aps)
    plan = build_recommendation_plan(request, existing_aps)

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
        default_unzoned_weight=request.default_unzoned_weight,
    )
    if not weighted_points:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "All evaluation points were excluded. Adjust excluded_zones or floor geometry.",
            400,
        )

    _attach_baseline_rssi(
        points=weighted_points,
        existing_aps=plan.baseline_aps,
        walls=walls,
        params=params,
        transfer=rssi_transfer,
    )

    n_movable = plan.movable_count

    logger.info(
        "AP recommendation start: scene=%s mode=%s candidates=%d eval=%d weighted=%d "
        "fixed_aps=%d movable=%d calibration=%s",
        sv.id,
        plan.mode,
        len(candidates),
        len(raw_eval_points),
        len(weighted_points),
        len(plan.fixed_aps),
        n_movable,
        rssi_transfer.method,
    )

    coverage_threshold = request.coverage_threshold_dbm or _DEFAULT_COVERAGE_THRESHOLD_DBM
    weak_zone_threshold = request.weak_zone_threshold_dbm or _DEFAULT_WEAK_ZONE_THRESHOLD_DBM

    # plan.fixed_aps already encodes the mode logic (targets removed, etc.).
    # Always use mode="add" internally — fixed_aps is the adjusted base.
    if n_movable == 1:
        top_results = _grid_search_topn(
            candidates=candidates,
            eval_points=weighted_points,
            existing_aps=plan.fixed_aps,
            walls=walls,
            params=params,
            transfer=rssi_transfer,
            recommendation_mode="add",
            replace_target_ap_id=None,
            candidate_tx_power_dbm=request.candidate_tx_power_dbm,
            coverage_threshold_dbm=coverage_threshold,
            weak_zone_threshold_dbm=weak_zone_threshold,
            target_bands=request.target_bands,
            combine_policy=request.combine_policy,
            n=request.n_recommendations,
        )
        recommendations = [
            _to_response_item(i + 1, x, y, metrics, predicted, ap_positions=[(x, y)])
            for i, (x, y, metrics, predicted) in enumerate(top_results)
        ]
        top_positions: list[tuple[float, float]] = (
            [(top_results[0][0], top_results[0][1])] if top_results else []
        )
    else:
        top_sets = _greedy_multi_ap(
            n_aps=n_movable,
            n_sets=request.n_recommendations,
            candidates=candidates,
            eval_points=weighted_points,
            existing_aps=plan.fixed_aps,
            walls=walls,
            params=params,
            transfer=rssi_transfer,
            candidate_tx_power_dbm=request.candidate_tx_power_dbm,
            coverage_threshold_dbm=coverage_threshold,
            weak_zone_threshold_dbm=weak_zone_threshold,
            target_bands=request.target_bands,
            combine_policy=request.combine_policy,
        )
        recommendations = [
            _to_response_item(
                i + 1,
                ap_set[0][0], ap_set[0][1],
                metrics, predicted,
                ap_positions=ap_set,
            )
            for i, (ap_set, metrics, predicted) in enumerate(top_sets)
        ]
        top_positions = top_sets[0][0] if top_sets else []

    relocation_moves = compute_relocation_moves(plan, top_positions)
    final_aps_list = compute_final_aps(plan, top_positions)

    leading_band = request.target_bands[0] if request.target_bands else "5G"
    response = ApRecommendationResponse(
        recommendations=recommendations,
        candidates_evaluated=len(candidates),
        eval_points_count=len(raw_eval_points),
        weighted_eval_points_count=len(weighted_points),
        calibration_applied=rssi_transfer.transfer_applied or best_params_applied,
        calibration=ApRecommendationCalibrationInfo(
            method=rssi_transfer.method,
            policy=request.calibration_policy,
            slope=round(rssi_transfer.slope, 6),
            intercept_db=round(rssi_transfer.intercept_db, 6),
            transfer_applied=rssi_transfer.transfer_applied,
            best_params_applied=best_params_applied,
            residual_used=rssi_transfer.residual_enabled,
            calibration_run_id=UUID(str(selected_calibration_run.id))
            if selected_calibration_run is not None
            else None,
        ),
        score_weights=SCORE_WEIGHTS,
        recommendation_mode=plan.mode,
        mode_explanation=plan.mode_explanation,
        baseline_aps_snapshot=[
            {"id": ap.name, "x": round(ap.x, 3), "y": round(ap.y, 3)}
            for ap in plan.baseline_aps
        ],
        fixed_aps_snapshot=[
            {"id": ap.name, "x": round(ap.x, 3), "y": round(ap.y, 3)}
            for ap in plan.fixed_aps
        ],
        movable_aps_snapshot=[
            {"id": ap_id, "x": round(x, 3), "y": round(y, 3)}
            for ap_id, (x, y) in zip(plan.movable_ap_ids, plan.movable_ap_coords)
        ],
        final_aps=final_aps_list,
        relocation_moves=relocation_moves,
        score_breakdown=(
            recommendations[0].score_breakdown if recommendations else {}
        ),
        physical_aps_snapshot=[ap.model_dump(mode="json") for ap in _physical_aps],
        band_metadata=build_band_metadata(_physical_aps, request.target_bands),
        recommendation_band=leading_band,
        band_aware_status=("full" if len(request.target_bands) > 1 else "leading_band_only"),
        residual_metadata=residual_metadata,
        verify_with_sionna=request.verify_with_sionna,
        verification_status=("pending" if request.verify_with_sionna else None),
        verification_jobs=[],
    )
    response.verification_jobs = await _submit_verification_jobs(
        db=db,
        scene_version=sv,
        request=request,
        recommendations=recommendations,
        plan=plan,
        current_user=current_user,
        enabled=request.verify_with_sionna,
        top_k=request.verification_top_k,
    )
    if request.verify_with_sionna:
        response.verification_status = (
            "running"
            if any(job.get("status") == "running" for job in response.verification_jobs)
            else "failed"
        )
    run = _persist_recommendation_run(
        db=db,
        scene_version=sv,
        request=request,
        response=response,
        calibration_run=selected_calibration_run,
    )
    response.run_id = UUID(str(run.id))
    response.created_at = run.created_at
    return response


def list_recommendation_runs(
    db: Session,
    *,
    scene_version_id: UUID,
    current_user: User,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResponse[ApRecommendationRunResponse]:
    sv = db.execute(
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(scene_version_id),
            Project.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if sv is None:
        raise AppError(ErrorCode.SCENE_VERSION_NOT_FOUND, "Scene version not found.", 404)

    stmt = select(ApRecommendationRun).where(
        ApRecommendationRun.scene_version_id == str(scene_version_id)
    )
    total = db.execute(
        select(func.count(ApRecommendationRun.id)).where(
            ApRecommendationRun.scene_version_id == str(scene_version_id)
        )
    ).scalar() or 0
    rows = (
        db.execute(
            stmt.order_by(ApRecommendationRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse[ApRecommendationRunResponse](
        items=[_run_to_response(row) for row in rows],
        page=page,
        page_size=page_size,
        total=int(total),
    )


def get_recommendation_run(
    db: Session,
    *,
    run_id: UUID,
    current_user: User,
) -> ApRecommendationRunResponse:
    row = (
        db.execute(
            select(ApRecommendationRun)
            .join(Project, ApRecommendationRun.project_id == Project.id)
            .where(
                ApRecommendationRun.id == str(run_id),
                Project.owner_user_id == current_user.id,
            )
        )
        .scalar_one_or_none()
    )
    if row is None:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "AP recommendation run not found.",
            404,
        )
    return _run_to_response(row)


def _persist_recommendation_run(
    *,
    db: Session,
    scene_version: SceneVersion,
    request: ApRecommendationRequest,
    response: ApRecommendationResponse,
    calibration_run: CalibrationRun | None,
) -> ApRecommendationRun:
    calibration = (
        response.calibration.model_dump(mode="json")
        if response.calibration is not None
        else {}
    )
    run = ApRecommendationRun(
        project_id=scene_version.project_id,
        floor_id=scene_version.floor_id,
        scene_version_id=scene_version.id,
        calibration_run_id=calibration_run.id if calibration_run is not None else None,
        status=response.status,
        request_json=request.model_dump(mode="json"),
        input_areas_json={
            "candidate_bboxes": [b.model_dump(mode="json") for b in request.candidate_bboxes],
            "evaluation_bboxes": [b.model_dump(mode="json") for b in request.evaluation_bboxes],
            "priority_zones": [z.model_dump(mode="json") for z in request.priority_zones],
            "excluded_zones": [b.model_dump(mode="json") for b in request.excluded_zones],
            "default_unzoned_weight": request.default_unzoned_weight,
        },
        existing_aps_json=list(request.existing_aps),
        calibration_json=calibration,
        score_weights_json=dict(response.score_weights),
        candidates_evaluated=response.candidates_evaluated,
        eval_points_count=response.eval_points_count,
        weighted_eval_points_count=response.weighted_eval_points_count,
    )
    db.add(run)
    db.flush()

    for item in response.recommendations:
        db.add(
            ApRecommendationItemRow(
                run_id=run.id,
                rank=item.rank,
                recommended_x=Decimal(str(item.recommended_x)),
                recommended_y=Decimal(str(item.recommended_y)),
                score=Decimal(str(item.score)),
                metrics_json=_item_metrics_json(item),
                prediction_points_json=[
                    p.model_dump(mode="json") for p in item.prediction_points
                ],
            )
        )

    db.commit()
    db.refresh(run)
    return run


def _item_metrics_json(item: ApRecommendationItem) -> dict[str, Any]:
    data = item.model_dump(mode="json", exclude={"prediction_points"})
    data.pop("rank", None)
    data.pop("recommended_x", None)
    data.pop("recommended_y", None)
    data.pop("score", None)
    return data


def _run_to_response(row: ApRecommendationRun) -> ApRecommendationRunResponse:
    return ApRecommendationRunResponse(
        id=row.id,
        project_id=row.project_id,
        floor_id=row.floor_id,
        scene_version_id=row.scene_version_id,
        calibration_run_id=row.calibration_run_id,
        status=row.status,
        request_json=row.request_json or {},
        input_areas_json=row.input_areas_json or {},
        existing_aps_json=row.existing_aps_json or [],
        calibration_json=row.calibration_json or {},
        score_weights_json=row.score_weights_json or {},
        candidates_evaluated=row.candidates_evaluated,
        eval_points_count=row.eval_points_count,
        weighted_eval_points_count=row.weighted_eval_points_count,
        recommendations=[_item_row_to_schema(item) for item in row.items],
        created_at=row.created_at,
    )


def _item_row_to_schema(row: ApRecommendationItemRow) -> ApRecommendationItem:
    metrics = row.metrics_json or {}
    return ApRecommendationItem(
        rank=row.rank,
        recommended_x=float(row.recommended_x),
        recommended_y=float(row.recommended_y),
        score=float(row.score),
        coverage_score=_float_or_none(metrics.get("coverage_score")),
        coverage_ratio=_float_or_none(metrics.get("coverage_ratio")),
        weak_zone_improvement_score=_float_or_none(
            metrics.get("weak_zone_improvement_score")
        ),
        weak_zone_improvement_db=_float_or_none(metrics.get("weak_zone_improvement_db")),
        bottom_10_percent_score=_float_or_none(metrics.get("bottom_10_percent_score")),
        bottom_10_percent_rssi_dbm=_float_or_none(
            metrics.get("bottom_10_percent_rssi_dbm")
        ),
        average_rssi_score=_float_or_none(metrics.get("average_rssi_score")),
        average_rssi_dbm=_float_or_none(metrics.get("average_rssi_dbm")),
        baseline_improvement_score=_float_or_none(
            metrics.get("baseline_improvement_score")
        ),
        baseline_improvement_db=_float_or_none(metrics.get("baseline_improvement_db")),
        score_breakdown=metrics.get("score_breakdown") or {},
        verified_score=_float_or_none(metrics.get("verified_score")),
        verification_status=(
            str(metrics.get("verification_status"))
            if metrics.get("verification_status") is not None
            else None
        ),
        verification_job_id=(
            UUID(str(metrics.get("verification_job_id")))
            if metrics.get("verification_job_id")
            else None
        ),
        prediction_points=[
            ApRecommendationPredictionPoint(**p)
            for p in (row.prediction_points_json or [])
            if isinstance(p, dict)
        ],
        ap_positions=[
            ApRecommendationApPosition(**p)
            for p in (metrics.get("ap_positions") or [])
            if isinstance(p, dict)
        ],
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _build_verification_job_placeholders(
    recommendations: list[ApRecommendationItem],
    *,
    enabled: bool,
    top_k: int,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    return [
        {
            "candidate_rank": item.rank,
            "candidate_id": f"cand-{item.rank}",
            "rf_job_id": None,
            "fast_score": item.score,
            "verified_score": None,
            "status": "deferred",
            "candidate_aps": [pos.model_dump(mode="json") for pos in item.ap_positions],
        }
        for item in recommendations[: max(1, top_k)]
    ]


async def _submit_verification_jobs(
    *,
    db: Session,
    scene_version: SceneVersion,
    request: ApRecommendationRequest,
    recommendations: list[ApRecommendationItem],
    plan: RecommendationPlan,
    current_user: User,
    enabled: bool,
    top_k: int,
) -> list[dict[str, Any]]:
    if not enabled:
        return []

    import asyncio
    from app.services.rf.rf_job_service import submit_rf_simulation
    from app.services.scene.scene_version_export import export_scene_version_to_scene_json
    from app.services.rf.calibration_worker.apply import (
        apply_to_scene_and_sim,
        get_latest_calibration,
    )

    leading_band = request.target_bands[0] if request.target_bands else "5G"
    simulation_template = _verification_simulation_payload(
        leading_band=leading_band,
        tx_power_dbm=request.candidate_tx_power_dbm,
    )

    # 모든 후보가 같은 scene_version 을 사용하므로 scene.json + 보정값을 1회만 계산
    scene_json = export_scene_version_to_scene_json(db, scene_version.id)
    calibration_meta: dict[str, Any] = {"applied": False}
    cr = get_latest_calibration(db, str(scene_version.id))
    if cr is not None:
        best_params = (cr.metrics_json or {}).get("best_params") or {}
        if best_params:
            summary = apply_to_scene_and_sim(scene_json, simulation_template, best_params)
            calibration_meta = {
                "applied": True,
                "calibration_run_id": cr.id,
                "summary": summary,
            }

    candidates = recommendations[: max(1, top_k)]

    # S3 + SageMaker invoke 는 asyncio.gather 로 병렬 제출
    # (DB 조회/쓰기는 각 submit_rf_simulation 내부에서 순차 처리됨)
    async def _submit_one(item: ApRecommendationItem) -> tuple[ApRecommendationItem, list, Any, Any]:
        top_positions = [(pos.x, pos.y) for pos in item.ap_positions]
        final_aps = compute_final_aps(plan, top_positions)
        access_points = _final_aps_to_verification_access_points(final_aps)
        rf_run, job = await submit_rf_simulation(
            db,
            scene_version_id=UUID(str(scene_version.id)),
            access_points=access_points,
            simulation=dict(simulation_template),
            current_user=current_user,
            run_type="ap_recommendation_verify",
            metadata={
                "source": "ap_recommendation_auto_verification",
                "recommendation_rank": item.rank,
                "recommendation_score": item.score,
                "recommendation_mode": plan.mode,
                "verification_top_k": top_k,
                "verification_backend": request.verification_backend,
                "target_bands": list(request.target_bands),
                "combine_policy": request.combine_policy,
                "candidate_aps": final_aps,
            },
            apply_calibration=False,
            backend=request.verification_backend,
            _prebuilt_scene_json=scene_json,
            _prebuilt_calibration_meta=calibration_meta,
        )
        return item, final_aps, rf_run, job

    results = await asyncio.gather(
        *[_submit_one(item) for item in candidates],
        return_exceptions=True,
    )

    jobs: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        item = candidates[i]
        top_positions = [(pos.x, pos.y) for pos in item.ap_positions]
        final_aps = compute_final_aps(plan, top_positions)
        job_payload: dict[str, Any] = {
            "candidate_rank": item.rank,
            "candidate_id": f"cand-{item.rank}",
            "rf_job_id": None,
            "rf_run_id": None,
            "fast_score": item.score,
            "verified_score": None,
            "status": "pending",
            "candidate_aps": final_aps,
        }

        if isinstance(result, Exception):
            logger.warning(
                "Failed to start AP recommendation verification job rank=%s scene=%s: %s",
                item.rank,
                scene_version.id,
                result,
            )
            job_payload.update({"status": "failed_to_start", "error": str(result)})
            item.verification_status = "failed_to_start"
            item.score_breakdown = {
                **(item.score_breakdown or {}),
                "verification_status": "failed_to_start",
                "verification_error": str(result),
            }
        else:
            _, _, rf_run, job = result
            job_payload.update(
                {
                    "rf_job_id": job.id,
                    "rf_run_id": rf_run.id,
                    "status": rf_run.status or "running",
                }
            )
            item.verification_job_id = UUID(str(job.id))
            item.verification_status = rf_run.status or "running"
            item.score_breakdown = {
                **(item.score_breakdown or {}),
                "verification_rf_run_id": rf_run.id,
                "verification_job_id": job.id,
                "verification_status": item.verification_status,
            }

        jobs.append(job_payload)

    return jobs


def _verification_simulation_payload(
    *,
    leading_band: str,
    tx_power_dbm: float,
) -> dict[str, Any]:
    frequency_hz = 2.437e9 if leading_band == "2.4G" else 5.18e9
    return {
        "frequency_hz": frequency_hz or DEFAULT_FREQUENCY_HZ,
        "tx_power_dbm": tx_power_dbm or DEFAULT_TX_POWER_DBM,
        # 검증용: 커버리지 분포 확인이 목적 → 정밀도보다 속도 우선.
        # diffraction/diffuse_reflection 끄면 10~50× 빨라짐.
        "samples_per_tx": 100_000,
        "max_depth": 5,
        "diffraction": False,
        "diffuse_reflection": False,
    }


def _final_aps_to_verification_access_points(
    final_aps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    access_points: list[dict[str, Any]] = []
    for index, ap in enumerate(final_aps):
        x = _float_or_none(ap.get("x"))
        y = _float_or_none(ap.get("y"))
        if x is None or y is None:
            continue
        ap_id = str(ap.get("id") or f"ap_{index + 1}")
        access_points.append(
            {
                "id": ap_id,
                "label": ap_id,
                "x_m": x,
                "y_m": y,
                "z_m": 2.5,
            }
        )
    return access_points


def _to_response_item(
    rank: int,
    x: float,
    y: float,
    metrics: CandidateMetrics,
    prediction_points: list[PredictedEvalPoint],
    ap_positions: list[tuple[float, float]] | None = None,
) -> ApRecommendationItem:
    positions = [
        ApRecommendationApPosition(ap_index=i + 1, x=round(px, 3), y=round(py, 3))
        for i, (px, py) in enumerate(ap_positions or [(x, y)])
    ]
    return ApRecommendationItem(
        rank=rank,
        recommended_x=round(x, 3),
        recommended_y=round(y, 3),
        score=round(metrics.final_score, 4),
        ap_positions=positions,
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
        score_breakdown=metrics.score_breakdown,
        prediction_points=[
            ApRecommendationPredictionPoint(
                x=round(p.x, 3),
                y=round(p.y, 3),
                rssi_dbm=round(p.candidate_rssi_dbm, 2),
                baseline_rssi_dbm=_round_optional(p.baseline_rssi_dbm, 2),
                weight=round(p.weight, 3),
            )
            for p in prediction_points
        ],
    )


def _greedy_multi_ap(
    *,
    n_aps: int,
    n_sets: int,
    candidates: list[tuple[float, float]],
    eval_points: list[WeightedEvalPoint],
    existing_aps: list[AccessPoint],
    walls: list[WallSegment],
    params: CalibrationParams,
    transfer: RssiTransfer,
    candidate_tx_power_dbm: float,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
    target_bands: list[str],
    combine_policy: str,
) -> list[tuple[list[tuple[float, float]], CandidateMetrics, list[PredictedEvalPoint]]]:
    """Greedy 방식으로 n_aps개 AP 세트를 n_sets개 생성.

    각 세트는 다음 방식으로 생성:
      1st AP: 단일 AP 탐색 상위 n_sets개 중 하나를 시작점으로
      2nd~nth AP: 이전까지 배치된 AP 고정 후 추가 효과 최대 위치 탐색
    """
    # 1단계: 1번 AP 후보 상위 n_sets개 추출
    top_first = _grid_search_topn(
        candidates=candidates,
        eval_points=eval_points,
        existing_aps=existing_aps,
        walls=walls,
        params=params,
        transfer=transfer,
        recommendation_mode="add",
        replace_target_ap_id=None,
        candidate_tx_power_dbm=candidate_tx_power_dbm,
        coverage_threshold_dbm=coverage_threshold_dbm,
        weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        target_bands=target_bands,
        combine_policy=combine_policy,
        n=n_sets,
    )

    result_sets: list[tuple[list[tuple[float, float]], CandidateMetrics, list[PredictedEvalPoint]]] = []

    for first_x, first_y, _, _ in top_first:
        ap_set: list[tuple[float, float]] = [(first_x, first_y)]
        current_aps = existing_aps + [
            AccessPoint(name=f"rec_{i+1}", x=px, y=py, tx_power_dbm=candidate_tx_power_dbm)
            for i, (px, py) in enumerate(ap_set)
        ]

        # 2번째 AP부터 greedy 추가
        for _ in range(n_aps - 1):
            available_candidates = [
                c
                for c in candidates
                if c not in ap_set
                and all(_distance_m(c, chosen) >= _MIN_RECOMMENDATION_SPACING_M for chosen in ap_set)
            ]
            # 간격 조건 충족 후보 없으면: 미사용 후보 중 기존 배치에서 가장 먼 것 순으로 폴백
            if not available_candidates:
                remaining = [c for c in candidates if c not in ap_set]
                if not remaining:
                    break
                remaining.sort(key=lambda c: -min(_distance_m(c, chosen) for chosen in ap_set))
                available_candidates = remaining
            next_results = _grid_search_topn(
                candidates=available_candidates,
                eval_points=eval_points,
                existing_aps=current_aps,
                walls=walls,
                params=params,
                transfer=transfer,
                recommendation_mode="add",
                replace_target_ap_id=None,
                candidate_tx_power_dbm=candidate_tx_power_dbm,
                coverage_threshold_dbm=coverage_threshold_dbm,
                weak_zone_threshold_dbm=weak_zone_threshold_dbm,
                target_bands=target_bands,
                combine_policy=combine_policy,
                n=1,
            )
            if not next_results:
                break
            nx, ny, _, _ = next_results[0]
            ap_set.append((nx, ny))
            current_aps.append(
                AccessPoint(name=f"rec_{len(ap_set)}", x=nx, y=ny, tx_power_dbm=candidate_tx_power_dbm)
            )

        # 최종 세트 전체 점수 계산
        final_results = _grid_search_topn(
            candidates=[ap_set[-1]],
            eval_points=eval_points,
            existing_aps=existing_aps + [
                AccessPoint(name=f"rec_{i+1}", x=px, y=py, tx_power_dbm=candidate_tx_power_dbm)
                for i, (px, py) in enumerate(ap_set[:-1])
            ],
            walls=walls,
            params=params,
            transfer=transfer,
            recommendation_mode="add",
            replace_target_ap_id=None,
            candidate_tx_power_dbm=candidate_tx_power_dbm,
            coverage_threshold_dbm=coverage_threshold_dbm,
            weak_zone_threshold_dbm=weak_zone_threshold_dbm,
            target_bands=target_bands,
            combine_policy=combine_policy,
            n=1,
        )
        if final_results:
            _, _, metrics, predicted = final_results[0]
            result_sets.append((ap_set, metrics, predicted))

    result_sets.sort(key=lambda t: t[1].final_score, reverse=True)

    # 순서 무관 중복 제거 — (AP1, AP2)와 (AP2, AP1)은 같은 세트로 처리
    seen: set[frozenset[tuple[float, float]]] = set()
    deduped = []
    for ap_set, metrics, predicted in result_sets:
        key = frozenset((round(x, 2), round(y, 2)) for x, y in ap_set)
        if key not in seen:
            seen.add(key)
            deduped.append((ap_set, metrics, predicted))

    return deduped[:n_sets]


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
            if any(_point_in_bbox(point[0], point[1], zone) for zone in request.excluded_zones):
                continue
            seen.add(key)
            candidates.append(point)
    return candidates


def _candidate_boxes_for_request(
    request: ApRecommendationRequest,
) -> list[ApRecommendationBBox]:
    if request.candidate_bboxes:
        return request.candidate_bboxes
    return _legacy_boxes_for_request(request)


def _legacy_boxes_for_request(
    request: ApRecommendationRequest,
) -> list[ApRecommendationBBox]:
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
    boxes = _evaluation_boxes_for_request(request)
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


def _evaluation_boxes_for_request(
    request: ApRecommendationRequest,
) -> list[ApRecommendationBBox]:
    """Fallback evaluation areas, ordered by scoring intent.

    Candidate boxes are installable AP areas, so they are only used as the last
    legacy fallback when the request gives no explicit evaluation scope.
    """
    if request.priority_zones:
        return request.priority_zones
    if request.evaluation_bboxes:
        return request.evaluation_bboxes
    legacy = _legacy_boxes_for_request(request)
    if legacy:
        return legacy
    return request.candidate_bboxes


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
    default_unzoned_weight: float = _DEFAULT_UNZONED_WEIGHT,
) -> list[WeightedEvalPoint]:
    weighted: list[WeightedEvalPoint] = []
    has_priority_zones = len(priority_zones) > 0
    default_weight = (
        max(0.0, min(1.0, default_unzoned_weight))
        if math.isfinite(default_unzoned_weight)
        else _DEFAULT_UNZONED_WEIGHT
    )
    for point in eval_points:
        if any(_point_in_bbox(point.x, point.y, zone) for zone in excluded_zones):
            continue
        weight = default_weight if has_priority_zones else 1.0
        label: str | None = None
        for zone in priority_zones:
            if _point_in_bbox(point.x, point.y, zone):
                zone_weight = _finite_float(getattr(zone, "weight", 1.0), 1.0)
                zone_weight = max(0.0, min(1.0, zone_weight))
                # Overlap rule: the strongest priority wins; ties keep first match.
                if zone_weight > weight or label is None:
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


def _select_calibration_run(
    db: Session,
    scene_version_id: str,
    calibration_run_id=None,
) -> CalibrationRun | None:
    if calibration_run_id is not None:
        return _get_calibration_for_scene_or_400(db, scene_version_id, calibration_run_id)
    return db.execute(
        select(CalibrationRun)
        .where(
            CalibrationRun.scene_version_id == str(scene_version_id),
            CalibrationRun.status == "completed",
        )
        .order_by(CalibrationRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _params_from_run(
    run: CalibrationRun | None,
    policy: CalibrationPolicy,
) -> CalibrationParams:
    if policy not in ("best_params_only", "combined"):
        return CalibrationParams()
    best = _find_best_params(run.metrics_json if run is not None else None)
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


def _best_params_applied(
    run: CalibrationRun | None,
    policy: CalibrationPolicy,
) -> bool:
    return policy in ("best_params_only", "combined") and bool(
        _find_best_params(run.metrics_json if run is not None else None)
    )


def _transfer_from_run(
    run: CalibrationRun | None,
    policy: CalibrationPolicy,
) -> RssiTransfer:
    if policy not in ("transfer_only", "combined"):
        return RssiTransfer()
    if run is None or not run.metrics_json:
        return RssiTransfer()

    calibration = _find_rssi_transfer_metrics(run.metrics_json)
    if not calibration:
        return RssiTransfer()

    slope = _finite_float(calibration.get("slope"), 1.0)
    intercept = _finite_float(
        calibration.get("intercept_db", calibration.get("intercept")),
        0.0,
    )
    if not math.isfinite(slope) or not math.isfinite(intercept):
        return RssiTransfer()
    transfer_applied = not (
        math.isclose(slope, 1.0, abs_tol=1e-9)
        and math.isclose(intercept, 0.0, abs_tol=1e-9)
    )
    return RssiTransfer(
        slope=slope,
        intercept_db=intercept,
        method=str(calibration.get("method") or "affine_rssi_transfer"),
        calibration_run_id=str(run.id),
        transfer_applied=transfer_applied,
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


def _find_best_params(metrics_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metrics_json, dict):
        return None
    best = metrics_json.get("best_params")
    if isinstance(best, dict):
        return best
    # Forward-compatible shape for future physical calibration records. Study-room
    # spaces may benefit from internal wall effective attenuation scale, but AP
    # recommendation does not tune path_loss_exp here to avoid overfitting.
    physical = metrics_json.get("physical_params")
    if isinstance(physical, dict):
        return physical
    return None


def _find_rssi_transfer_metrics(metrics_json: dict[str, Any]) -> dict[str, Any] | None:
    transfer = metrics_json.get("rssi_transfer")
    if isinstance(transfer, dict):
        return transfer
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


def _compute_residual_transfer(
    db: Session,
    floor_id: str,
    scene_version_id: str,
    transfer: RssiTransfer,
    residual_weight: float = 0.5,
) -> RssiTransfer:
    """실측 데이터와 Sionna 예측으로 spatial residual map 계산 후 transfer에 추가.

    1. 최신 completed 측정 세션에서 실측 RSSI 로드
    2. Sionna radio_map에서 각 측정점의 예측값 bilinear 보간
    3. (실측 - linear_corrected_pred) = 잔차 계산
    4. GP로 잔차를 dense grid로 보간
    5. RssiTransfer에 residual grid 추가 후 반환

    측정 데이터나 Sionna 결과가 없으면 원래 transfer 그대로 반환.
    """
    import numpy as np
    from app.core.geom import wkb_to_geojson
    from app.models.measurement_point import MeasurementPoint
    from app.models.measurement_session import MeasurementSession
    from app.models.rf_run import RfRun

    # 1) 최신 completed 측정 세션 + 포인트 로드 (현재 scene_version 우선, 없으면 같은 층 전체)
    session = db.execute(
        select(MeasurementSession)
        .where(
            MeasurementSession.scene_version_id == scene_version_id,
            MeasurementSession.status == "completed",
        )
        .order_by(MeasurementSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if session is None:
        session = db.execute(
            select(MeasurementSession)
            .where(
                MeasurementSession.floor_id == floor_id,
                MeasurementSession.status == "completed",
            )
            .order_by(MeasurementSession.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if session is None:
        return transfer

    meas_rows = db.execute(
        select(MeasurementPoint).where(
            MeasurementPoint.session_id == session.id,
            MeasurementPoint.rssi_dbm.isnot(None),
        )
    ).scalars().all()
    if len(meas_rows) < 3:
        return transfer

    meas_pts: list[tuple[float, float, float]] = []
    for p in meas_rows:
        gj = wkb_to_geojson(p.point_geom)
        coords = (gj or {}).get("coordinates") or []
        if len(coords) >= 2:
            meas_pts.append((float(coords[0]), float(coords[1]), float(p.rssi_dbm)))

    # 2) Sionna radio_map 로드 (현재 scene_version 우선, 없으면 같은 층 전체)
    rf_run = db.execute(
        select(RfRun)
        .where(
            RfRun.scene_version_id == scene_version_id,
            RfRun.status.in_(["done", "completed", "succeeded"]),
        )
        .order_by(RfRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rf_run is None:
        rf_run = db.execute(
            select(RfRun)
            .where(
                RfRun.floor_id == floor_id,
                RfRun.status.in_(["done", "completed", "succeeded"]),
            )
            .order_by(RfRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if rf_run is None:
        return transfer

    radio_map = (rf_run.metrics_json or {}).get("radio_map") or {}
    values = radio_map.get("values_dbm")
    bounds = radio_map.get("bounds_m") or {}
    if not isinstance(values, list) or not values:
        return transfer

    try:
        sim_grid = np.asarray(values, dtype=np.float64)
    except Exception:
        return transfer
    if sim_grid.ndim != 2 or sim_grid.size == 0:
        return transfer

    H, W = sim_grid.shape
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", float(W)))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", float(H)))
    if max_x <= min_x or max_y <= min_y:
        return transfer

    sim_xs = np.linspace(min_x, max_x, W)
    sim_ys = np.linspace(min_y, max_y, H)

    # 3) 측정점마다 잔차 계산
    residual_pts: list[tuple[float, float, float]] = []
    for mx, my, actual in meas_pts:
        ix = int(np.searchsorted(sim_xs, mx, side="right")) - 1
        iy = int(np.searchsorted(sim_ys, my, side="right")) - 1
        ix = min(max(ix, 0), W - 2)
        iy = min(max(iy, 0), H - 2)
        tx = (mx - sim_xs[ix]) / (sim_xs[ix + 1] - sim_xs[ix] + 1e-9)
        ty = (my - sim_ys[iy]) / (sim_ys[iy + 1] - sim_ys[iy] + 1e-9)
        sionna_pred = (
            sim_grid[iy,     ix    ] * (1 - tx) * (1 - ty)
            + sim_grid[iy,     ix + 1] * tx       * (1 - ty)
            + sim_grid[iy + 1, ix    ] * (1 - tx) * ty
            + sim_grid[iy + 1, ix + 1] * tx       * ty
        )
        if not math.isfinite(sionna_pred) or sionna_pred < -200:
            continue
        corrected_pred = apply_rssi_transfer(float(sionna_pred), transfer)
        residual = actual - corrected_pred
        residual_pts.append((mx, my, residual))

    if len(residual_pts) < 3:
        return transfer

    # 포인트 수에 따라 weight 조정 — 적을수록 GP 신뢰도 낮음
    n_pts = len(residual_pts)
    if n_pts < 10:
        effective_weight = residual_weight * 0.5
    elif n_pts < 20:
        effective_weight = residual_weight * 0.75
    else:
        effective_weight = residual_weight

    # 4) GP로 잔차 보간
    try:
        from app.services.rf.measurement_estimation.gp_estimator import estimate_coverage
        from app.services.rf.calibration_worker.path_loss import Measurement as M

        gp_input = [(x, y, r) for x, y, r in residual_pts]
        estimate = estimate_coverage(
            gp_input,
            bounds=(min_x, min_y, max_x, max_y),
            grid_resolution_m=1.0,
        )
        residual_grid = estimate.mean_grid
        residual_xs = estimate.xs
        residual_ys = estimate.ys
    except Exception as exc:
        logger.warning("Residual GP failed (%s) — skipping residual correction", exc)
        return transfer

    logger.info(
        "Residual correction computed: %d measurement points → grid %s",
        len(residual_pts), residual_grid.shape,
    )

    return RssiTransfer(
        slope=transfer.slope,
        intercept_db=transfer.intercept_db,
        method=transfer.method + "+residual",
        calibration_run_id=transfer.calibration_run_id,
        transfer_applied=True,
        residual_enabled=True,
        residual_weight=effective_weight,
        residual_grid=residual_grid,
        residual_xs=residual_xs,
        residual_ys=residual_ys,
    )


def _finite_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _physical_aps_to_access_points(
    physical_aps: list,  # list[PhysicalApInput]
    candidate_tx_power_dbm: float = 20.0,
) -> list[AccessPoint]:
    """PhysicalApInput list → 경로 손실 모델용 AccessPoint list.

    현재는 AP별 leading radio(첫 번째 활성 radio)를 single-band 기준으로 변환한다.
    TODO: band별 scoring 완성 후 band-aware AccessPoint로 확장.
    """
    result: list[AccessPoint] = []
    for ap in physical_aps:
        radios = ap.effective_radios()
        leading = radios[0] if radios else None
        result.append(
            AccessPoint(
                name=str(ap.id or ap.name or f"ap_{id(ap)}"),
                x=ap.x,
                y=ap.y,
                tx_power_dbm=(
                    leading.effective_tx_power_dbm(candidate_tx_power_dbm)
                    if leading else candidate_tx_power_dbm
                ),
            )
        )
    return result


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


def _validate_mode_targets(
    request: ApRecommendationRequest,
    existing_aps: list[AccessPoint],
) -> None:
    """Validate that AP IDs referenced in mode-specific fields exist in existing_aps."""
    existing_names = {ap.name for ap in existing_aps}
    if request.recommendation_mode == "replace":
        targets = list(request.replace_target_ap_ids or [])
        if request.replace_target_ap_id and request.replace_target_ap_id not in targets:
            targets.append(request.replace_target_ap_id)
        if not targets:
            return
        label = "replace target AP"
    elif request.recommendation_mode == "relocate_selected":
        targets = list(request.relocate_target_ap_ids or [])
        for movable_id in request.movable_ap_ids:
            if movable_id not in targets:
                targets.append(movable_id)
        if not targets:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                "relocate_selected requires at least one movable AP id.",
                400,
            )
        overlap = set(targets) & set(request.fixed_ap_ids or [])
        if overlap:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                f"AP ids cannot be both fixed and movable: {sorted(overlap)}.",
                400,
            )
        label = "relocate target AP"
    else:
        return
    for target in targets:
        if target not in existing_names:
            raise AppError(
                ErrorCode.INVALID_REQUEST_BODY,
                f"{label} '{target}' was not found in existing_aps.",
                400,
            )


def _validate_replace_target(
    request: ApRecommendationRequest,
    existing_aps: list[AccessPoint],
) -> None:
    """Backward-compatible wrapper for older tests and callers."""
    _validate_mode_targets(request, existing_aps)


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
        point.baseline_rssi_dbm = apply_rssi_transfer(raw, transfer, x=point.x, y=point.y)


def apply_rssi_transfer(
    raw_pred: float,
    transfer: RssiTransfer,
    x: float | None = None,
    y: float | None = None,
) -> float:
    corrected = transfer.slope * raw_pred + transfer.intercept_db
    if (
        transfer.residual_enabled
        and transfer.residual_grid is not None
        and transfer.residual_xs is not None
        and transfer.residual_ys is not None
        and x is not None
        and y is not None
    ):
        residual = _interpolate_residual(
            x, y,
            transfer.residual_grid,
            transfer.residual_xs,
            transfer.residual_ys,
        )
        corrected += residual * transfer.residual_weight
    return corrected


def _apply_band_aware_scoring(
    points: list[PredictedEvalPoint],
    *,
    target_bands: list[str],
    combine_policy: str,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
) -> list[PredictedEvalPoint]:
    active_bands = target_bands or ["5G"]
    if len(active_bands) == 1:
        band = active_bands[0]
        return [
            PredictedEvalPoint(
                x=p.x,
                y=p.y,
                weight=p.weight,
                zone_label=p.zone_label,
                baseline_rssi_dbm=p.baseline_rssi_dbm,
                candidate_rssi_dbm=_project_rssi_to_band(p.candidate_rssi_dbm, band),
            )
            for p in points
        ]

    return [
        PredictedEvalPoint(
            x=p.x,
            y=p.y,
            weight=p.weight,
            zone_label=p.zone_label,
            baseline_rssi_dbm=p.baseline_rssi_dbm,
            candidate_rssi_dbm=combine_band_values(
                _project_rssi_to_band(p.candidate_rssi_dbm, "5G"),
                _project_rssi_to_band(p.candidate_rssi_dbm, "2.4G"),
                combine_policy if combine_policy in ("max", "prefer_5g_then_2g", "weighted") else "prefer_5g_then_2g",
                threshold_5g_dbm=max(-75.0, coverage_threshold_dbm - 3.0),
            ),
        )
        for p in points
    ]


def _band_scores_for_points(
    band_source_points: list[PredictedEvalPoint],
    overall_points: list[PredictedEvalPoint],
    *,
    target_bands: list[str],
    combine_policy: str,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
) -> dict[str, Any]:
    map_5g = [[_project_rssi_to_band(p.candidate_rssi_dbm, "5G") for p in band_source_points]]
    map_2g = [[_project_rssi_to_band(p.candidate_rssi_dbm, "2.4G") for p in band_source_points]]
    overall_map = [[p.candidate_rssi_dbm for p in overall_points]]
    summary = compute_band_quality_summary(
        map_5g if "5G" in target_bands else None,
        map_2g if "2.4G" in target_bands else None,
        overall_map,
        coverage_threshold_dbm=coverage_threshold_dbm,
        weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        combine_policy=combine_policy if combine_policy in ("max", "prefer_5g_then_2g", "weighted") else "prefer_5g_then_2g",
    )
    return summary


def _project_rssi_to_band(rssi_dbm: float, band: str) -> float:
    """Approximate fast path-loss RSSI for a target band.

    The current fast scorer is not a full frequency-aware ray tracer. This keeps
    the path fast while making combine_policy affect score selection. Sionna
    verification remains the high-fidelity path for final candidates.
    """
    if band == "2.4G":
        return min(-30.0, rssi_dbm + 4.0)
    return rssi_dbm


def _build_score_breakdown(metrics: CandidateMetrics) -> dict[str, Any]:
    return {
        "coverage_score": metrics.coverage_score,
        "coverage_ratio": metrics.coverage_ratio,
        "weak_zone_improvement": metrics.weak_zone_improvement_db,
        "weak_zone_improvement_score": metrics.weak_zone_improvement_score,
        "weak_zone_improvement_db": metrics.weak_zone_improvement_db,
        "bottom_10_percent": metrics.bottom_10_percent_rssi_dbm,
        "bottom_10_percent_score": metrics.bottom_10_percent_score,
        "bottom_10_percent_rssi_dbm": metrics.bottom_10_percent_rssi_dbm,
        "average_rssi": metrics.average_rssi_dbm,
        "average_rssi_score": metrics.average_rssi_score,
        "average_rssi_dbm": metrics.average_rssi_dbm,
        "baseline_improvement": metrics.baseline_improvement_db,
        "baseline_improvement_score": metrics.baseline_improvement_score,
        "baseline_improvement_db": metrics.baseline_improvement_db,
    }


def _interpolate_residual(
    x: float, y: float,
    grid: "np.ndarray",
    xs: "np.ndarray",
    ys: "np.ndarray",
) -> float:
    """residual grid에서 (x, y) 위치의 값을 bilinear interpolation으로 추출."""
    import numpy as np
    if x < xs[0] or x > xs[-1] or y < ys[0] or y > ys[-1]:
        return 0.0
    ix = int(np.searchsorted(xs, x, side="right")) - 1
    iy = int(np.searchsorted(ys, y, side="right")) - 1
    ix = min(max(ix, 0), len(xs) - 2)
    iy = min(max(iy, 0), len(ys) - 2)
    tx = (x - xs[ix]) / (xs[ix + 1] - xs[ix] + 1e-9)
    ty = (y - ys[iy]) / (ys[iy + 1] - ys[iy] + 1e-9)
    val = (
        grid[iy,     ix    ] * (1 - tx) * (1 - ty)
        + grid[iy,     ix + 1] * tx       * (1 - ty)
        + grid[iy + 1, ix    ] * (1 - tx) * ty
        + grid[iy + 1, ix + 1] * tx       * ty
    )
    return float(val) if math.isfinite(float(val)) else 0.0


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
    replace_target_ap_id: str | None,
    candidate_tx_power_dbm: float,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
    target_bands: list[str],
    combine_policy: str,
    n: int,
) -> list[tuple[float, float, CandidateMetrics, list[PredictedEvalPoint]]]:
    scored: list[tuple[float, float, CandidateMetrics, list[PredictedEvalPoint]]] = []

    for cx, cy in candidates:
        test_ap = AccessPoint(
            name=replace_target_ap_id or "candidate",
            x=cx,
            y=cy,
            tx_power_dbm=_finite_float(candidate_tx_power_dbm, 20.0),
        )
        eval_aps = _aps_for_candidate(
            existing_aps=existing_aps,
            candidate_ap=test_ap,
            recommendation_mode=recommendation_mode,
            replace_target_ap_id=replace_target_ap_id,
        )
        predicted: list[PredictedEvalPoint] = []
        for point in eval_points:
            raw = predict_rssi_best_ap(eval_aps, _as_measurement(point), walls, params)
            calibrated = apply_rssi_transfer(raw, transfer, x=point.x, y=point.y)
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
        scored_predicted = _apply_band_aware_scoring(
            predicted,
            target_bands=target_bands,
            combine_policy=combine_policy,
            coverage_threshold_dbm=coverage_threshold_dbm,
            weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        )
        metrics = compute_ap_recommendation_metrics(
            scored_predicted,
            coverage_threshold_dbm=coverage_threshold_dbm,
            weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        )
        metrics.score_breakdown = _build_score_breakdown(metrics)
        metrics.score_breakdown["band_scores"] = _band_scores_for_points(
            predicted,
            scored_predicted,
            target_bands=target_bands,
            combine_policy=combine_policy,
            coverage_threshold_dbm=coverage_threshold_dbm,
            weak_zone_threshold_dbm=weak_zone_threshold_dbm,
        )
        scored.append((cx, cy, metrics, scored_predicted))

    scored.sort(
        key=lambda t: (
            t[2].final_score,
            t[2].coverage_score,
            t[2].bottom_10_percent_score,
            t[2].average_rssi_score,
        ),
        reverse=True,
    )
    return _select_diverse_topn(scored, n=n, min_distance_m=_MIN_RECOMMENDATION_SPACING_M)


def _select_diverse_topn(
    scored: list[tuple[float, float, CandidateMetrics, list[PredictedEvalPoint]]],
    *,
    n: int,
    min_distance_m: float,
) -> list[tuple[float, float, CandidateMetrics, list[PredictedEvalPoint]]]:
    if n <= 0:
        return []
    selected: list[tuple[float, float, CandidateMetrics, list[PredictedEvalPoint]]] = []
    for item in scored:
        point = (item[0], item[1])
        if all(_distance_m(point, (picked[0], picked[1])) >= min_distance_m for picked in selected):
            selected.append(item)
            if len(selected) >= n:
                return selected
    for item in scored:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= n:
            break
    return selected


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _aps_for_candidate(
    *,
    existing_aps: list[AccessPoint],
    candidate_ap: AccessPoint,
    recommendation_mode: str,
    replace_target_ap_id: str | None,
) -> list[AccessPoint]:
    if recommendation_mode == "add":
        return existing_aps + [candidate_ap]
    # replace without a target is the legacy "evaluate candidate AP only" mode.
    if not replace_target_ap_id:
        return [candidate_ap]
    kept = [ap for ap in existing_aps if ap.name != replace_target_ap_id]
    if len(kept) == len(existing_aps):
        logger.warning(
            "AP replacement target %s not found; evaluating candidate only.",
            replace_target_ap_id,
        )
        return [candidate_ap]
    return kept + [candidate_ap]


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

"""Schemas for AP placement recommendation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rf.physical_ap import BandLiteral, PhysicalApInput


class ApRecommendationBBox(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x_min: float
    x_max: float
    y_min: float
    y_max: float


class ApRecommendationZone(ApRecommendationBBox):
    label: str | None = None
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class ApRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scene_version_id: UUID

    # Legacy single bbox. Optional so new clients can use candidate_bboxes only.
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    target_bboxes: list[dict[str, float]] = Field(default_factory=list)

    candidate_bboxes: list[ApRecommendationBBox] = Field(default_factory=list)
    evaluation_bboxes: list[ApRecommendationBBox] = Field(default_factory=list)
    priority_zones: list[ApRecommendationZone] = Field(default_factory=list)
    excluded_zones: list[ApRecommendationBBox] = Field(default_factory=list)
    default_unzoned_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    step_m: float = Field(default=1.0, gt=0.0, le=5.0)
    existing_aps: list[dict[str, Any]] = Field(default_factory=list)

    # ── Physical AP / Radio Interface 구조 (신규) ────────────
    # physical_aps가 있으면 existing_aps보다 우선한다.
    # 없으면 기존 existing_aps를 내부에서 PhysicalApInput으로 변환한다.
    physical_aps: list[PhysicalApInput] = Field(default_factory=list)
    # 추천 단위: 현재는 physical_ap만 지원. radio 단위 추천은 후속 작업.
    recommendation_unit: Literal["physical_ap"] = "physical_ap"
    # 시뮬 대상 band 우선순위. 현재 추천은 leading band 단일 시뮬로 동작한다.
    # TODO: band별 scoring 완성 후 멀티 band 평가 지원
    target_bands: list[BandLiteral] = Field(default_factory=lambda: ["5G", "2.4G"])
    # band 결과 통합 정책
    # max: cell별 max RSSI
    # prefer_5g_then_2g: 5G 가용 시 5G, 아니면 2.4G
    # weighted: 가중 평균 (후속 작업)
    combine_policy: Literal["max", "prefer_5g_then_2g", "weighted"] = "prefer_5g_then_2g"

    calibration_run_id: UUID | None = None
    calibration_policy: Literal["transfer_only", "best_params_only", "combined"] = (
        "transfer_only"
    )
    recommendation_mode: Literal["add", "replace", "relocate_all", "relocate_selected"] = "add"
    replace_target_ap_id: str | None = None
    # Multi-target replace: list of AP IDs to swap out simultaneously.
    replace_target_ap_ids: list[str] = Field(default_factory=list)
    # relocate_selected: IDs that stay fixed (never moved).
    fixed_ap_ids: list[str] = Field(default_factory=list)
    # relocate_selected: IDs to relocate.
    relocate_target_ap_ids: list[str] = Field(default_factory=list)
    # add mode: explicit count of new APs to add (overrides n_aps when > 0).
    additional_ap_count: int = Field(default=0, ge=0, le=5)
    # relocate_all mode: total number of APs in the new layout.
    target_total_aps: int | None = Field(default=None, ge=1, le=10)
    candidate_tx_power_dbm: float = 20.0
    coverage_threshold_dbm: float = -67.0
    weak_zone_threshold_dbm: float = -67.0

    # Deprecated legacy fields. Kept for request compatibility.
    shadow_threshold_dbm: float = Field(default=-80.0)
    shadow_penalty: float = Field(default=100.0)
    n_recommendations: int = Field(default=3, ge=1, le=10)
    # 멀티 AP 추천 — 한 번에 설치할 AP 수
    n_aps: int = Field(default=1, ge=1, le=5)


class ApRecommendationApPosition(BaseModel):
    """멀티 AP 세트 내 개별 AP 위치."""
    model_config = ConfigDict(extra="forbid")

    ap_index: int
    x: float
    y: float


class ApRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    recommended_x: float
    recommended_y: float
    score: float
    # 멀티 AP일 때 전체 위치 목록 (n_aps=1이면 1개)
    ap_positions: list[ApRecommendationApPosition] = Field(default_factory=list)
    coverage_score: float | None = None
    coverage_ratio: float | None = None
    weak_zone_improvement_score: float | None = None
    weak_zone_improvement_db: float | None = None
    bottom_10_percent_score: float | None = None
    bottom_10_percent_rssi_dbm: float | None = None
    average_rssi_score: float | None = None
    average_rssi_dbm: float | None = None
    baseline_improvement_score: float | None = None
    baseline_improvement_db: float | None = None
    prediction_points: list["ApRecommendationPredictionPoint"] = Field(default_factory=list)


class ApRecommendationPredictionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float
    rssi_dbm: float
    baseline_rssi_dbm: float | None = None
    weight: float = 1.0


class ApRecommendationCalibrationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    policy: Literal["transfer_only", "best_params_only", "combined"] = "transfer_only"
    slope: float
    intercept_db: float
    transfer_applied: bool = False
    best_params_applied: bool = False
    residual_used: bool = False
    calibration_run_id: UUID | None = None


class ApRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID | None = None
    recommendations: list[ApRecommendationItem]
    status: str = "success"
    candidates_evaluated: int
    eval_points_count: int | None = None
    weighted_eval_points_count: int | None = None
    calibration_applied: bool = False
    calibration: ApRecommendationCalibrationInfo | None = None
    score_weights: dict[str, float] = Field(default_factory=dict)
    created_at: datetime | None = None

    # ── Recommendation mode metadata ────────────────────────────────────────
    recommendation_mode: str = "add"
    mode_explanation: str = ""
    # All existing APs before any moves (for before/after comparison).
    baseline_aps_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    # APs that stayed fixed (not moved).
    fixed_aps_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    # APs that were replaced / relocated.
    movable_aps_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    # Final AP layout for the top recommendation (fixed + recommended).
    final_aps: list[dict[str, Any]] = Field(default_factory=list)
    # Per-AP move records: {ap_id, from_x, from_y, to_x, to_y}.
    relocation_moves: list[dict[str, Any]] = Field(default_factory=list)

    # ── Physical AP / band 메타데이터 ────────────────────────
    # 추천에 사용된 physical AP 목록 스냅샷
    physical_aps_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    # band별 시뮬 정보 (어떤 band/radio가 사용됐는지)
    band_metadata: dict[str, Any] = Field(default_factory=dict)
    # 추천이 어떤 band 기준으로 수행됐는지
    recommendation_band: str | None = None
    # coverage semantics 설명
    coverage_semantics: dict[str, Any] = Field(
        default_factory=lambda: {
            "multi_ap_rssi_merge": "max_per_cell",
            "rssi_is_not_summed": True,
            "note": (
                "복수 AP/radio의 RSSI는 합산되지 않습니다. "
                "cell별 coverage는 max(rssi per radio)로 평가합니다. "
                "채널/혼잡 완화 효과는 별도 capacity/congestion 관점으로 다룹니다."
            ),
        }
    )


class ApRecommendationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    floor_id: UUID
    scene_version_id: UUID
    calibration_run_id: UUID | None = None
    status: str
    request_json: dict[str, Any] = Field(default_factory=dict)
    input_areas_json: dict[str, Any] = Field(default_factory=dict)
    existing_aps_json: list[dict[str, Any]] = Field(default_factory=list)
    calibration_json: dict[str, Any] = Field(default_factory=dict)
    score_weights_json: dict[str, float] = Field(default_factory=dict)
    candidates_evaluated: int
    eval_points_count: int | None = None
    weighted_eval_points_count: int | None = None
    recommendations: list[ApRecommendationItem] = Field(default_factory=list)
    created_at: datetime

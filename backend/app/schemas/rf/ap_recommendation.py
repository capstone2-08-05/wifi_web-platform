"""Schemas for AP placement recommendation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    calibration_run_id: UUID | None = None
    calibration_policy: Literal["transfer_only", "best_params_only", "combined"] = (
        "transfer_only"
    )
    recommendation_mode: Literal["add", "replace"] = "add"
    replace_target_ap_id: str | None = None
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

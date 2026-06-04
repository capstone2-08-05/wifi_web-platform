"""Schemas for AP placement recommendation."""
from __future__ import annotations

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


class ApRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    recommended_x: float
    recommended_y: float
    score: float
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

    recommendations: list[ApRecommendationItem]
    status: str = "success"
    candidates_evaluated: int
    eval_points_count: int | None = None
    weighted_eval_points_count: int | None = None
    calibration_applied: bool = False
    calibration: ApRecommendationCalibrationInfo | None = None
    score_weights: dict[str, float] = Field(default_factory=dict)

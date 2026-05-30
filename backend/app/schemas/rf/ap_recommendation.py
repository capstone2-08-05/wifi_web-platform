"""AP 최적 위치 추천 스키마"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_version_id: UUID
    # 사용자가 드래그한 탐색 영역 (미터 단위)
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    # 격자 간격 (기본 1m)
    step_m: float = Field(default=1.0, gt=0.0, le=5.0)
    # 기존 AP 리스트 — 이미 배치된 AP의 간섭/보완 효과 반영
    existing_aps: list[dict[str, Any]] = Field(default_factory=list)
    # 보정 파라미터 출처 (없으면 기본값)
    calibration_run_id: UUID | None = None
    # 음영 기준선 (기본 -80 dBm)
    shadow_threshold_dbm: float = Field(default=-80.0)
    # 음영 패널티 점수
    shadow_penalty: float = Field(default=100.0)
    # 반환할 추천 개수
    n_recommendations: int = Field(default=3, ge=1, le=10)


class ApRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    recommended_x: float
    recommended_y: float
    score: float


class ApRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[ApRecommendationItem]
    status: str = "success"
    candidates_evaluated: int

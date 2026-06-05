"""§11 Calibration DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import normalize_job_status

# SpaceType 의 string 값들을 Literal 로 받아 Pydantic 검증 — runner 의 resolve_space_type
# 이 unknown fallback 처리하므로 빠져도 안전하지만 typo 는 여기서 차단.
SpaceTypeLiteral = Literal[
    "cafe", "study_room", "classroom", "office", "residential", "unknown"
]

MeasurementPurposeLiteral = Literal["calibration", "validation", "reference", "unknown"]


class CalibrationRunCreate(BaseModel):
    """POST /calibration-runs — 명세 §11.1"""
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    rf_run_id: UUID
    version_id: UUID
    # 공간 유형 (soft prior). 미지정 시 backend runner 가 "unknown" 으로 fallback.
    space_type: Optional[SpaceTypeLiteral] = None


class CalibrationEvaluationSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["purpose_or_random", "random"] = "purpose_or_random"
    holdout_ratio: float = Field(default=0.3, gt=0.0, lt=1.0)
    seed: int = 42


class CalibrationEvaluationVisualization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_reference_map: bool = True
    reference_map_method: Literal["idw"] = "idw"
    rssi_min_dbm: float = -90.0
    rssi_max_dbm: float = -30.0


class CalibrationEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor_id: UUID
    scene_version_id: UUID
    rf_run_id: UUID
    measurement_session_ids: list[UUID] = Field(default_factory=list, min_length=1)
    ap_bssid: str | None = None
    method: Literal["affine_rssi_transfer", "global_offset"] = "affine_rssi_transfer"
    split: CalibrationEvaluationSplit = Field(default_factory=CalibrationEvaluationSplit)
    visualization: CalibrationEvaluationVisualization = Field(
        default_factory=CalibrationEvaluationVisualization
    )


class CalibrationEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration_run_id: UUID
    status: str
    maps: dict[str, Any]
    color_scale: dict[str, float]
    points: dict[str, list[dict[str, Any]]]
    metrics: dict[str, float]
    evaluation: dict[str, Any]


class CalibrationRunResponse(BaseModel):
    """GET /calibration-runs/{id} 응답 — 명세 §11.2

    모델 컬럼명과 명세 필드명이 다른 부분은 service 의 _to_response 에서 alias 매핑.
    """
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    session_id: Optional[UUID] = None
    rf_run_id: Optional[UUID] = None
    version_id: UUID
    error_metrics_json: dict[str, Any] = Field(default_factory=dict)
    error_heatmap_url: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        """내부 status(completed/queued) → API 표기(succeeded/pending). 프론트 폴링 종료 인식용."""
        if isinstance(v, str):
            return normalize_job_status(v)
        return v


class CalibrationRunUpdate(BaseModel):
    """[시스템] PATCH /calibration-runs/{id} — AI 워커가 진행 상태 갱신."""
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    metrics_json: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


class ParameterUpdateCreate(BaseModel):
    """[시스템] POST /calibration-runs/{id}/parameter-updates"""
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(..., min_length=1, max_length=20)
    target_id: UUID
    param_name: str = Field(..., min_length=1, max_length=80)
    old_value_json: Any | None = None
    new_value_json: Any | None = None

    @model_validator(mode="after")
    def _at_least_one_value(self):
        # 새 값 정도는 있어야 의미 있음 (old 만 있으면 정보 부족).
        if self.new_value_json is None and self.old_value_json is None:
            raise ValueError("at least one of old_value_json/new_value_json required")
        return self


class ParameterUpdateResponse(BaseModel):
    """§11.3 응답 항목. DB 컬럼 parameter_name 을 param_name 으로 노출."""
    model_config = ConfigDict(extra="forbid")

    id: UUID
    calibration_run_id: UUID
    target_type: str
    target_id: UUID
    param_name: str
    old_value_json: Any | None = None
    new_value_json: Any | None = None
    created_at: datetime

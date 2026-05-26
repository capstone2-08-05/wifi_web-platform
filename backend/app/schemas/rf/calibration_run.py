"""§11 Calibration DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CalibrationRunCreate(BaseModel):
    """POST /calibration-runs — 명세 §11.1"""
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    rf_run_id: UUID
    version_id: UUID


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

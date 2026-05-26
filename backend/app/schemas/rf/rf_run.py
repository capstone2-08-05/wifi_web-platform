"""RF Run DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, conlist, field_validator

from typing import Literal

from app.core.enums import normalize_job_status
from app.core.rf_defaults import (
    DEFAULT_FREQUENCY_HZ,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MEASUREMENT_PLANE_Z_M,
    DEFAULT_RESOLUTION_M,
    DEFAULT_SAMPLES_PER_TX,
    DEFAULT_SEED,
    DEFAULT_TX_POWER_DBM,
)

RfBackend = Literal["sagemaker", "local"]


# ============================================================
# RF 시뮬레이션 submit DTO
# ============================================================
class AccessPointDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,32}$")
    x_m: float
    y_m: float
    z_m: float


class RfSimulationParams(BaseModel):
    """RF 시뮬 파라미터. 모든 필드 optional — 미지정 시 `app/core/rf_defaults.py` 값 적용.

    프론트엔드는 사용자가 명시적으로 정한 값만 보내면 됨 (예: AP 가 정해진 frequency band).
    Solver 하이퍼파라미터 (max_depth, samples_per_tx 등) 는 보통 backend 디폴트 그대로.
    """
    model_config = ConfigDict(extra="forbid")

    frequency_hz: float = Field(default=DEFAULT_FREQUENCY_HZ, gt=0)
    tx_power_dbm: float = DEFAULT_TX_POWER_DBM
    resolution_m: float = Field(default=DEFAULT_RESOLUTION_M, gt=0)
    measurement_plane_z_m: float = DEFAULT_MEASUREMENT_PLANE_Z_M
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=0)
    samples_per_tx: int = Field(default=DEFAULT_SAMPLES_PER_TX, ge=1000)
    seed: int = DEFAULT_SEED


class RfRunCreate(BaseModel):
    """POST /rf-runs 요청.

    기존 호환을 위해 access_points/simulation 은 optional. 둘 다 없으면 단순
    queue 등록 (sagemaker invoke 안 함) — 추후 deprecate 예정.
    """
    model_config = ConfigDict(extra="forbid")

    scene_version_id: UUID
    run_type: Optional[str] = None
    access_points: Optional[conlist(AccessPointDTO, min_length=1, max_length=8)] = None  # type: ignore[valid-type]
    simulation: Optional[RfSimulationParams] = None
    metadata: Optional[dict[str, Any]] = None
    # 해당 scene_version 의 최신 completed CalibrationRun 보정값을 시뮬에 반영할지 (#88).
    # true(기본): 보정 적용 / false: raw 시뮬 (보정 전후 비교용).
    apply_calibration: bool = True
    # 시뮬 실행 백엔드 선택. sagemaker(기본)=클라우드 async, local=로컬 ai_api 직접 호출.
    backend: RfBackend = "sagemaker"
    # 옛 호출자 호환 (deprecated)
    request_json: Optional[dict[str, Any]] = None


class RfRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    floor_id: UUID
    scene_version_id: UUID
    run_type: str
    status: str
    request_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        """내부 status → API 표기 (done/completed → succeeded 등). DB 값은 유지."""
        if isinstance(v, str):
            return normalize_job_status(v)
        return v


class RfRunCreatedResponse(RfRunResponse):
    job_id: UUID


class RfRunUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    metrics_json: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


# ============================================================
# GET /rf-jobs/{job_id} — 폴링 응답
# ============================================================
class RfJobError(BaseModel):
    backend_code: str
    container_code: Optional[str] = None
    stage: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class RfJobOutputUri(BaseModel):
    s3_uri: str
    url: Optional[str] = None  # presigned URL (TTL 적용)


class RfJobResponse(BaseModel):
    """RF Job 폴링 응답. result.* 필드는 succeeded 일 때만 채워짐."""

    job_id: UUID
    rf_run_id: Optional[UUID] = None
    status: str  # API 표기: "pending" | "running" | "succeeded" | "failed"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output_prefix: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    heatmap: Optional[RfJobOutputUri] = None
    radio_map: Optional[RfJobOutputUri] = None
    error: Optional[RfJobError] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        """내부 status(running/done/failed) → API 표기로 통일. DB 값은 유지."""
        if isinstance(v, str):
            return normalize_job_status(v)
        return v

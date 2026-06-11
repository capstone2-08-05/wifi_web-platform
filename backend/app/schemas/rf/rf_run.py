"""RF Run DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, conlist, field_validator

from app.core.enums import normalize_job_status
from app.schemas.rf.physical_ap import BandLiteral, PhysicalApInput
from app.core.rf_defaults import (
    DEFAULT_DIFFRACTION,
    DEFAULT_DIFFUSE_REFLECTION,
    DEFAULT_FREQUENCY_HZ,
    DEFAULT_LOS,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MEASUREMENT_PLANE_Z_M,
    DEFAULT_REFRACTION,
    DEFAULT_RESOLUTION_M,
    DEFAULT_SAMPLES_PER_TX,
    DEFAULT_SEED,
    DEFAULT_SPECULAR_REFLECTION,
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
    Solver/propagation 하이퍼파라미터는 보통 backend 디폴트 그대로.
    """
    model_config = ConfigDict(extra="forbid")

    # 물리값
    frequency_hz: float = Field(default=DEFAULT_FREQUENCY_HZ, gt=0)
    tx_power_dbm: float = DEFAULT_TX_POWER_DBM
    # 측정 grid
    resolution_m: float = Field(default=DEFAULT_RESOLUTION_M, gt=0)
    measurement_plane_z_m: float = DEFAULT_MEASUREMENT_PLANE_Z_M
    # Solver
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=0)
    samples_per_tx: int = Field(default=DEFAULT_SAMPLES_PER_TX, ge=1000)
    seed: int = DEFAULT_SEED
    # Propagation mechanisms — ai_api PropagationConfig 와 매핑.
    los: bool = DEFAULT_LOS
    specular_reflection: bool = DEFAULT_SPECULAR_REFLECTION
    refraction: bool = DEFAULT_REFRACTION
    diffuse_reflection: bool = DEFAULT_DIFFUSE_REFLECTION
    diffraction: bool = DEFAULT_DIFFRACTION


class BandSimulationParams(BaseModel):
    """band별 RF run 파라미터 (신규).

    현재는 bands 목록과 combine_policy만 지원한다.
    실제 band별 Sionna run은 각 band의 leading radio frequency를 사용한다.

    TODO: band별 calibration slope/intercept 분리 적용
    TODO: overall_quality_map (2.4G/5G 통합 맵) 생성
    """
    model_config = ConfigDict(extra="forbid")

    bands: list[BandLiteral] = Field(default_factory=lambda: ["5G"])
    combine_policy: Literal["max", "prefer_5g_then_2g", "weighted"] = "prefer_5g_then_2g"


class RfRunCreate(BaseModel):
    """POST /rf-runs 요청.

    기존 호환을 위해 access_points/simulation 은 optional. 둘 다 없으면 단순
    queue 등록 (sagemaker invoke 안 함) — 추후 deprecate 예정.

    신규: physical_aps로 Physical AP + Radio Interface 구조를 직접 전달할 수 있다.
    physical_aps가 있으면 access_points보다 우선한다.
    """
    model_config = ConfigDict(extra="forbid")

    scene_version_id: UUID
    run_type: Optional[str] = None
    access_points: Optional[conlist(AccessPointDTO, min_length=1, max_length=8)] = None  # type: ignore[valid-type]
    simulation: Optional[RfSimulationParams] = None
    metadata: Optional[dict[str, Any]] = None
    # 해당 scene_version 의 최신 completed CalibrationRun 보정값을 시뮬에 반영할지 (#88).
    # 기본은 raw 시뮬레이션이다. 보정 후 재실행처럼 의도가 명확한 요청만 true 로 보낸다.
    apply_calibration: bool = False
    # 시뮬 실행 백엔드 선택. sagemaker(기본)=클라우드 async, local=로컬 ai_api 직접 호출.
    backend: RfBackend = "local"
    # 옛 호출자 호환 (deprecated)
    request_json: Optional[dict[str, Any]] = None

    # ── Physical AP / Radio Interface 구조 (신규) ────────────
    # physical_aps가 있으면 access_points보다 우선해 transmitter list를 빌드한다.
    physical_aps: list[PhysicalApInput] = Field(default_factory=list)
    # band별 시뮬 파라미터 — 미지정 시 single band (5G default) 로 동작한다.
    band_simulation: Optional[BandSimulationParams] = None


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

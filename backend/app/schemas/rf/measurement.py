from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_serializer


def _utc_iso_z(value: datetime) -> str:
    utc = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


class MeasurementLinkCreateResponseDTO(BaseModel):
    token: str
    expires_at: datetime
    deep_link: str
    web_fallback_url: str
    qr_payload: str

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> str:
        return _utc_iso_z(value)


class FloorplanInfoDTO(BaseModel):
    url: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    scale_m_per_px: float | None = None


class CoordinateSystemDTO(BaseModel):
    unit: str = "meter"
    origin: str = "top_left"
    x_axis: str = "right"
    y_axis: str = "down"
    z_axis: str = "up"


class FloorBoundsDTO(BaseModel):
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0


class MeasurementLinkContextResponseDTO(BaseModel):
    token: str
    project_id: str
    floor_id: str
    scene_version_id: str | None = None
    asset_id: str | None = None
    expires_at: datetime
    floorplan: FloorplanInfoDTO = Field(default_factory=FloorplanInfoDTO)
    coordinate_system: CoordinateSystemDTO = Field(default_factory=CoordinateSystemDTO)
    bounds: FloorBoundsDTO = Field(default_factory=FloorBoundsDTO)
    anchor_points: list[dict[str, Any]] = Field(default_factory=list)
    existing_ap_layouts: list[dict[str, Any]] = Field(default_factory=list)
    recommended_measurement_purpose: str = "calibration"

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> str:
        return _utc_iso_z(value)


class FloorPositionDTO(BaseModel):
    x: float
    y: float
    z: float = 0.0


class WifiScanResultDTO(BaseModel):
    """Single Wi-Fi scan result sent by the Android measurement client.

    These values are kept separate from RSSI calibration. They are raw material
    for channel/capacity/congestion analysis.
    """

    model_config = ConfigDict(populate_by_name=True)

    bssid: str | None = None
    ssid: str | None = None
    rssi_dbm: float | None = Field(default=None, validation_alias=AliasChoices("rssi_dbm", "rssiDbm", "level"))
    channel: int | None = None
    frequency_mhz: int | None = Field(default=None, validation_alias=AliasChoices("frequency_mhz", "frequencyMhz", "frequency"))
    band: str | None = None
    channel_width_mhz: int | None = Field(default=None, validation_alias=AliasChoices("channel_width_mhz", "channelWidthMhz", "channelWidth"))
    center_frequency_mhz: int | None = Field(default=None, validation_alias=AliasChoices("center_frequency_mhz", "centerFrequencyMhz", "centerFreq0"))
    security: str | None = None
    capabilities: str | None = None


class DeviceInfoDTO(BaseModel):
    model: str | None = None
    os: str | None = None
    app_version: str | None = None


class CalibrationDTO(BaseModel):
    method: str | None = None
    start_floor_position: FloorPositionDTO | None = None
    initial_heading_deg: float | None = None


class MeasurementSessionCreateRequestDTO(BaseModel):
    measurement_link_token: str
    measurement_type: str = "rssi"
    measurement_purpose: Literal["calibration", "validation", "reference", "unknown"] = "unknown"
    device_info: DeviceInfoDTO = Field(default_factory=DeviceInfoDTO)
    calibration: CalibrationDTO = Field(default_factory=CalibrationDTO)


class MeasurementSessionResponseDTO(BaseModel):
    id: str
    project_id: str
    floor_id: str
    scene_version_id: str | None = None
    asset_id: str | None = None
    measurement_type: str
    measurement_purpose: str = "unknown"
    status: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return _utc_iso_z(value)


class MeasurementPointInputDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_point_id: str | None = None
    floor_position: FloorPositionDTO
    rssi_dbm: float | None = None
    sinr_db: float | None = Field(default=None, validation_alias=AliasChoices("sinr_db", "sinrDb"))
    latency_ms: float | None = Field(default=None, validation_alias=AliasChoices("latency_ms", "latencyMs"))
    throughput_mbps: float | None = Field(default=None, validation_alias=AliasChoices("throughput_mbps", "throughputMbps"))
    measurement_purpose: Literal["calibration", "validation", "reference", "unknown"] | None = None
    ap_bssid: str | None = None
    ap_ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = Field(default=None, validation_alias=AliasChoices("frequency_mhz", "frequencyMhz", "frequency"))
    channel_width_mhz: int | None = Field(default=None, validation_alias=AliasChoices("channel_width_mhz", "channelWidthMhz", "channelWidth"))
    center_frequency_mhz: int | None = Field(default=None, validation_alias=AliasChoices("center_frequency_mhz", "centerFrequencyMhz", "centerFreq0"))
    link_speed_mbps: float | None = Field(default=None, validation_alias=AliasChoices("link_speed_mbps", "linkSpeedMbps", "linkSpeed"))
    tx_link_speed_mbps: float | None = Field(default=None, validation_alias=AliasChoices("tx_link_speed_mbps", "txLinkSpeedMbps"))
    rx_link_speed_mbps: float | None = Field(default=None, validation_alias=AliasChoices("rx_link_speed_mbps", "rxLinkSpeedMbps"))
    noise_dbm: float | None = Field(default=None, validation_alias=AliasChoices("noise_dbm", "noiseDbm"))
    wifi_standard: str | None = Field(default=None, validation_alias=AliasChoices("wifi_standard", "wifiStandard"))
    wifi_scan_results: list[WifiScanResultDTO] = Field(
        default_factory=list,
        validation_alias=AliasChoices("wifi_scan_results", "wifiScanResults", "scan_results", "scanResults"),
    )
    timestamp_at_point: datetime | None = None
    ar_tracking_state: str | None = None
    ar_confidence: float | None = None
    step_index: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class MeasurementPointBatchRequestDTO(BaseModel):
    batch_id: str | None = None
    points: list[MeasurementPointInputDTO]


class MeasurementPointBatchResponseDTO(BaseModel):
    inserted: int
    duplicated: int
    session_status: str


class MeasurementSessionCompleteRequestDTO(BaseModel):
    end_position: FloorPositionDTO | None = None


class RssiRangeDTO(BaseModel):
    min: float | None = None
    max: float | None = None
    avg: float | None = None


class MeasurementSessionCompleteResponseDTO(BaseModel):
    id: str
    status: str
    total_points: int
    duration_seconds: int
    ap_count: int
    rssi_range: RssiRangeDTO


# ============================================================
# §10.4 / §10.5 조회 응답 DTO
# ============================================================
class MeasurementPointResponseDTO(BaseModel):
    """§10.4 — 측정 포인트 단건 조회 응답."""
    id: str
    session_id: str
    client_point_id: str | None = None
    batch_id: str | None = None
    floor_position: FloorPositionDTO
    rssi_dbm: float | None = None
    sinr_db: float | None = None
    latency_ms: float | None = None
    throughput_mbps: float | None = None
    measurement_purpose: str | None = None
    ap_bssid: str | None = None
    ap_ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    timestamp_at_point: datetime | None = None
    ar_tracking_state: str | None = None
    ar_confidence: float | None = None
    step_index: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_serializer("timestamp_at_point", "created_at", when_used="unless-none")
    def _serialize_dt(self, value: datetime) -> str:
        return _utc_iso_z(value)


class DetectedApResponseDTO(BaseModel):
    """§10.5 — 세션 내에서 측정된 고유 AP 집계."""
    ap_bssid: str
    ap_ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    point_count: int
    rssi_avg: float | None = None
    rssi_min: float | None = None
    rssi_max: float | None = None


# ============================================================
# GP 보간 응답 (#81)
# ============================================================
class EstimatedRssiRangeDTO(BaseModel):
    min: float
    max: float
    mean: float


class EstimatedCoverageResponseDTO(BaseModel):
    """GP regression 결과. mean/uncertainty heatmap presigned URL + 메타."""
    heatmap_url: str           # 평균 RSSI heatmap (presigned)
    uncertainty_url: str       # 불확실성 (std) heatmap (presigned)
    bounds: FloorBoundsDTO     # 도면 좌표 영역
    grid_shape: list[int]      # [H, W]
    grid_resolution_m: float
    rssi_range: EstimatedRssiRangeDTO  # 추정 grid 의 min/max/mean (dBm)
    uncertainty_max_db: float
    input_point_count: int     # GP 학습에 쓴 측정점 개수
    kernel_repr: str           # 학습된 kernel 정보 (디버깅)
    method: str = "gp_only"    # 'gp_only' (sim 없음) | 'residual_kriging' (sim prior 사용)
    coverage_threshold_dbm: float = -67.0
    coverage_ratio: float | None = None
    coverage_score: float | None = None
    average_rssi_dbm: float | None = None
    bottom_10_percent_rssi_dbm: float | None = None

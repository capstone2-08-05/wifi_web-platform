from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_serializer


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

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> str:
        return _utc_iso_z(value)


class FloorPositionDTO(BaseModel):
    x: float
    y: float
    z: float = 0.0


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
    device_info: DeviceInfoDTO = Field(default_factory=DeviceInfoDTO)
    calibration: CalibrationDTO = Field(default_factory=CalibrationDTO)


class MeasurementSessionResponseDTO(BaseModel):
    id: str
    project_id: str
    floor_id: str
    scene_version_id: str | None = None
    asset_id: str | None = None
    measurement_type: str
    status: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return _utc_iso_z(value)


class MeasurementPointInputDTO(BaseModel):
    client_point_id: str | None = None
    floor_position: FloorPositionDTO
    rssi_dbm: float | None = None
    ap_bssid: str | None = None
    ap_ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
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

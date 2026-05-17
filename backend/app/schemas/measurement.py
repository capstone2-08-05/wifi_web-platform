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
    """측정 좌표계 규약.

    heading_zero_axis / heading_positive_direction 는 모바일이 입력하는
    initial_heading_deg 의 의미를 명시한다 (이전엔 정의 없음).
      - heading_zero_axis = "x"  → heading=0° 일 때 사용자 정면이 floor +x 방향
      - heading_positive_direction = "cw" → heading 증가 시 시각적 시계방향
        (y_axis=down 좌표계에서 +x → +y 로 회전)
    """
    unit: str = "meter"
    origin: str = "top_left"
    x_axis: str = "right"
    y_axis: str = "down"
    z_axis: str = "up"
    heading_zero_axis: str = "x"
    heading_positive_direction: str = "cw"


class FloorBoundsDTO(BaseModel):
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0


class SceneGeometryRoomDTO(BaseModel):
    id: str
    room_name: str | None = None
    room_type: str | None = None
    polygon_geom: dict[str, Any] | None = None  # GeoJSON Polygon
    centroid_geom: dict[str, Any] | None = None  # GeoJSON Point


class SceneGeometryWallDTO(BaseModel):
    id: str
    wall_role: str
    thickness_m: float | None = None
    height_m: float | None = None
    centerline_geom: dict[str, Any] | None = None  # GeoJSON LineString
    polygon_geom: dict[str, Any] | None = None     # GeoJSON Polygon (있으면)


class SceneGeometryOpeningDTO(BaseModel):
    id: str
    opening_type: str
    width_m: float | None = None
    height_m: float | None = None
    sill_height_m: float | None = None
    line_geom: dict[str, Any] | None = None        # GeoJSON LineString


class SceneGeometryObjectDTO(BaseModel):
    id: str
    object_type: str
    confidence: float | None = None
    z_m: float | None = None
    point_geom: dict[str, Any] | None = None       # GeoJSON Point


class SceneGeometryDTO(BaseModel):
    """SceneVersion 기준 분석 결과(방/벽/출입구/객체)를 도면 좌표계 위에 표현.

    모든 좌표는 floor 좌표계 (origin=top_left, +x=right, +y=down, unit=meter).
    값들은 GeoJSON 으로 직렬화되어 모바일/프론트가 그대로 도면 위에 그릴 수 있게 함.
    """
    rooms: list[SceneGeometryRoomDTO] = Field(default_factory=list)
    walls: list[SceneGeometryWallDTO] = Field(default_factory=list)
    openings: list[SceneGeometryOpeningDTO] = Field(default_factory=list)
    objects: list[SceneGeometryObjectDTO] = Field(default_factory=list)


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
    geometry: SceneGeometryDTO = Field(default_factory=SceneGeometryDTO)
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

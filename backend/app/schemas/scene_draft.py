from __future__ import annotations

from pydantic import BaseModel

from app.schemas.scene import SceneSchema

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field


class UploadStorageMetadataDTO(BaseModel):
    provider: str = "local"
    original_filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    local_saved_path: str | None = None
    s3_uri: str | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None


class SaveSceneDraftRequestDTO(BaseModel):
    scene: SceneSchema
    upload: UploadStorageMetadataDTO
    project_id: str | None = None
    floor_id: str | None = None
    created_by: str | None = None


class SaveSceneDraftResultDTO(BaseModel):
    scene_draft_id: str


class SceneDraftUpdateRequest(BaseModel):
    """PATCH /scene-drafts/{id} — summary_json 일부 필드 갱신.

    현재는 사용자가 도면 편집기에서 한 벽·문/창의 실측값으로 전체를 재스케일할 때
    summary_json["scale_ratio_m_per_px"] 와 wall_postprocess.scale_source 를 같이
    갱신하는 용도. 좌표 PATCH(/draft-walls, /draft-openings, ...) 와 묶여 호출.
    """
    scale_ratio_m_per_px: float | None = None
    # 예: "manual_rescale" (사용자가 실측 입력 후 scale 버튼).
    scale_source: str | None = None


class SceneDraftRescaleRequest(BaseModel):
    """POST /scene-drafts/{id}/rescale — 한 트랜잭션 안에서 draft 전체 비례 재스케일.

    프론트에서 entity 별로 PATCH 를 N번 보내던 흐름을 단일 요청으로 통합.
    백엔드가 walls·openings·rooms·objects geometry 및 dependent metadata 를 일괄 곱하고,
    summary_json.scale_ratio_m_per_px 도 같이 ×factor.

    factor: 실측값 / 현재 도형 길이. 1.0 이면 no-op. 범위 (0.001, 1000) 강제.
    scale_source: 보통 "manual_rescale" — summary.wall_postprocess.scale_source 에 기록.
    """
    factor: float
    scale_source: str | None = None


class AnalyzeFromAssetRequest(BaseModel):
    """POST /assets/{asset_id}/analyze 본문.

    real_width_m 은 제거됨 (백엔드의 OCR 치수 자동 추정으로 대체).
    inference_mode 만 옵션으로 노출.
    """
    model_config = ConfigDict(extra="forbid")

    inference_mode: Literal["sagemaker", "local"] = "sagemaker"


class SceneDraftCreateRequest(BaseModel):
    """POST /floors/{floor_id}/scene-drafts — 빈 Draft 생성.

    AI 분석 없이 사용자가 도면을 처음부터 그릴 때 사용.
    현재는 "manual" 만 허용. 추후 다른 source_mode 추가 시 enum 확장.
    """
    model_config = ConfigDict(extra="forbid")

    source_mode: Literal["manual"] = Field(default="manual")


class SubmitFloorplanJobResponse(BaseModel):
    """도면 분석 비동기 Job 제출 공통 응답 (HTTP 202).

    완료/진행 상태는 GET /floorplan-jobs/{job_id} 로 폴링.
    """

    status: str = "submitted"
    job_id: str
    project_id: str | None = None
    floor_id: str | None = None
    job_status: str
    sagemaker_inference_id: str | None = None
    poll_url: str


class UploadAndAnalyzeFloorplanResponse(SubmitFloorplanJobResponse):
    """POST /upload/floorplan/analyze 응답."""

    fileId: str
    savedPath: str


class AnalyzeFromAssetResponse(SubmitFloorplanJobResponse):
    """POST /assets/{asset_id}/analyze 응답."""

    asset_id: str

# ============================================
# 단건 조회 응답 (GET /scene-drafts/{id})
# ============================================

class DraftRoomResponse(BaseModel):
    id: str
    scene_draft_id: str
    room_name: str | None
    room_type: str | None
    confidence: Decimal | None
    source_method: str | None
    polygon_geom: dict[str, Any] | None = None
    centroid_geom: dict[str, Any] | None = None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftWallResponse(BaseModel):
    id: str
    scene_draft_id: str
    wall_role: str
    thickness_m: Decimal
    height_m: Decimal | None
    material_label: str | None
    confidence: Decimal | None
    source_method: str | None
    centerline_geom: dict[str, Any] | None = None
    polygon_geom: dict[str, Any] | None = None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftOpeningResponse(BaseModel):
    id: str
    scene_draft_id: str
    wall_id: str | None
    opening_type: str
    width_m: Decimal
    height_m: Decimal
    sill_height_m: Decimal | None
    confidence: Decimal | None
    source_method: str | None
    line_geom: dict[str, Any] | None = None
    polygon_geom: dict[str, Any] | None = None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftObjectResponse(BaseModel):
    id: str
    scene_draft_id: str
    object_type: str
    confidence: Decimal | None
    source_method: str | None
    point_geom: dict[str, Any] | None = None
    z_m: Decimal | None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SceneDraftDetailResponse(BaseModel):
    id: str
    project_id: str
    floor_id: str
    source_mode: str
    source_asset_id: str | None
    source_method: str | None
    summary_json: dict[str, Any]
    status: str
    rooms: list[DraftRoomResponse]
    walls: list[DraftWallResponse]
    openings: list[DraftOpeningResponse]
    objects: list[DraftObjectResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SceneDraftSummaryResponse(BaseModel):
    
    id: str
    project_id: str
    floor_id: str
    source_mode: str
    source_asset_id: str | None
    source_method: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
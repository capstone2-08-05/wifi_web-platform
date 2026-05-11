from __future__ import annotations

from pydantic import BaseModel

from app.schemas.scene import SceneSchema

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict


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


class AnalyzeFromAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real_width_m: float = 10.0


class AnalyzeFromAssetResponse(BaseModel):
    status: str
    scene_draft_id: str
    asset_id: str
    scene: SceneSchema

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
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftObjectResponse(BaseModel):
    id: str
    scene_draft_id: str
    object_type: str
    confidence: Decimal | None
    source_method: str | None
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
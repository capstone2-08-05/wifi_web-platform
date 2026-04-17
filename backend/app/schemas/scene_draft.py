from __future__ import annotations

from pydantic import BaseModel

from app.schemas.scene import SceneSchema


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

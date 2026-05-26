"""Scene Version 도메인 DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scene.opening import OpeningResponse
from app.schemas.scene.room import RoomResponse
from app.schemas.scene.scene_object import ObjectResponse
from app.schemas.scene.wall import WallResponse


class PromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_no: int = Field(..., ge=1)
    is_current: bool = True


class SceneVersionResponse(BaseModel):
    id: UUID
    project_id: UUID
    floor_id: UUID
    source_draft_id: Optional[UUID] = None
    version_no: int
    is_current: bool
    source_mode: str
    source_method: Optional[str] = None
    source_asset_id: Optional[UUID] = None
    render_scene_url: Optional[str] = None
    rf_scene_url: Optional[str] = None
    artifacts_json: dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime


class SceneVersionDetailResponse(SceneVersionResponse):
    rooms: list[RoomResponse] = Field(default_factory=list)
    walls: list[WallResponse] = Field(default_factory=list)
    openings: list[OpeningResponse] = Field(default_factory=list)
    objects: list[ObjectResponse] = Field(default_factory=list)

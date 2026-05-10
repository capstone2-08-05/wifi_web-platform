"""Room (확정본) DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoomResponse(BaseModel):
    id: UUID
    scene_version_id: UUID
    room_name: Optional[str] = None
    room_type: Optional[str] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    polygon_geom: Optional[dict[str, Any]] = None
    centroid_geom: Optional[dict[str, Any]] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

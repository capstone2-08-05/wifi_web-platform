"""Opening (확정본) DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OpeningResponse(BaseModel):
    id: UUID
    scene_version_id: UUID
    wall_id: Optional[UUID] = None
    opening_type: str
    width_m: Decimal
    height_m: Decimal
    sill_height_m: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    line_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

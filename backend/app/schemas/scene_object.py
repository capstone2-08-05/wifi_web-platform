"""Scene Object (확정본) DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ObjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: Optional[str] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    point_geom: Optional[dict[str, Any]] = None
    z_m: Optional[Decimal] = None
    metadata_json: Optional[dict[str, Any]] = None


class ObjectResponse(BaseModel):
    id: UUID
    scene_version_id: UUID
    object_type: str
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    point_geom: Optional[dict[str, Any]] = None
    z_m: Optional[Decimal] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

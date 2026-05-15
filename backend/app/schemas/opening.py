"""Opening (확정본) DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OpeningUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall_id: Optional[UUID] = None
    opening_type: Optional[str] = None
    width_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    sill_height_m: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    line_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: Optional[dict[str, Any]] = None


class OpeningCreate(BaseModel):
    """확정본 Scene Version 에 새 Opening 추가용 (POST /scene-versions/{id}/openings).

    opening_type / width_m / height_m 은 NOT NULL 컬럼 — 누락 시 사용자에게 에러.
    """

    model_config = ConfigDict(extra="forbid")

    wall_id: Optional[UUID] = None
    opening_type: str
    width_m: Decimal
    height_m: Decimal
    sill_height_m: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    line_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: Optional[dict[str, Any]] = None


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

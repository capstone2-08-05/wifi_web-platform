"""Draft Wall 도메인 DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DraftWallCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall_role: Optional[str] = None
    thickness_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    material_label: Optional[str] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    centerline_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: Optional[dict[str, Any]] = None


class DraftWallUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall_role: Optional[str] = None
    thickness_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    material_label: Optional[str] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    centerline_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: Optional[dict[str, Any]] = None


class DraftWallResponse(BaseModel):
    id: UUID
    scene_draft_id: UUID
    wall_role: str
    thickness_m: Decimal
    height_m: Optional[Decimal] = None
    material_label: Optional[str] = None
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    centerline_geom: Optional[dict[str, Any]] = None
    polygon_geom: Optional[dict[str, Any]] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

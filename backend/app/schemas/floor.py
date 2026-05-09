"""
Floor 도메인 DTO
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ============================================
# Request DTO
# ============================================
class FloorCreateRequest(BaseModel):
    floor_name: str = Field(min_length=1, max_length=80)
    floor_order: int = Field(default=0)
    height_m: Decimal = Field(default=Decimal("2.4"), gt=0, le=Decimal("99.999"))


class FloorUpdateRequest(BaseModel):
    floor_name: str | None = Field(default=None, min_length=1, max_length=80)
    floor_order: int | None = None
    height_m: Decimal | None = Field(default=None, gt=0, le=Decimal("99.999"))


# ============================================
# Response DTO 
# ============================================
class FloorResponse(BaseModel):

    id: str
    project_id: str
    floor_name: str = Field(
        validation_alias="name",
        serialization_alias="floor_name",
    )
    floor_order: int = Field(
        validation_alias="floor_index",
        serialization_alias="floor_order",
    )
    height_m: Decimal = Field(
        validation_alias="default_ceiling_height_m",
        serialization_alias="height_m",
    )
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )
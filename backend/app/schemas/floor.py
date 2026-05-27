"""
Floor 도메인 DTO
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SpaceTypeLiteral = Literal[
    "cafe", "study_room", "classroom", "office", "residential", "unknown"
]


# ============================================
# Request DTO
# ============================================
class FloorCreateRequest(BaseModel):
    floor_name: str = Field(min_length=1, max_length=80)
    floor_order: int = Field(default=0)
    height_m: Decimal = Field(default=Decimal("2.4"), gt=0, le=Decimal("99.999"))
    space_type: SpaceTypeLiteral | None = None


class FloorUpdateRequest(BaseModel):
    floor_name: str | None = Field(default=None, min_length=1, max_length=80)
    floor_order: int | None = None
    height_m: Decimal | None = Field(default=None, gt=0, le=Decimal("99.999"))
    # 공간 유형 변경. 'unknown' 도 명시 가능, null/생략 시 미변경 (PATCH 시맨틱).
    space_type: SpaceTypeLiteral | None = None


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
    space_type: SpaceTypeLiteral = "unknown"
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )
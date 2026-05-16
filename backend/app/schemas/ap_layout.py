"""AP Layout DTO (§14)"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApLayoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rf_run_id: UUID
    ap_name: str = Field(..., min_length=1, max_length=60)
    vendor_model: Optional[str] = Field(default=None, max_length=60)
    point_geom: dict[str, Any]
    z_m: float
    azimuth_deg: float = 0
    tilt_deg: float = 0
    power_dbm: Optional[float] = None
    channel_info_json: dict[str, Any] = Field(default_factory=dict)


class ApLayoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ap_name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    vendor_model: Optional[str] = Field(default=None, max_length=60)
    point_geom: Optional[dict[str, Any]] = None
    z_m: Optional[float] = None
    azimuth_deg: Optional[float] = None
    tilt_deg: Optional[float] = None
    power_dbm: Optional[float] = None
    channel_info_json: Optional[dict[str, Any]] = None


class ApLayoutResponse(BaseModel):
    id: UUID
    rf_run_id: UUID
    ap_name: str
    vendor_model: Optional[str] = None
    point_geom: Optional[dict[str, Any]] = None
    z_m: Decimal
    azimuth_deg: Decimal
    tilt_deg: Decimal
    power_dbm: Optional[Decimal] = None
    channel_info_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

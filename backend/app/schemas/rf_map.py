"""RF Map DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RfMapCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_type: str
    resolution_cm: int
    storage_url: str
    bounds_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)


class RfMapResponse(BaseModel):
    id: UUID
    rf_run_id: UUID
    map_type: str
    resolution_cm: int
    storage_url: str
    bounds_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

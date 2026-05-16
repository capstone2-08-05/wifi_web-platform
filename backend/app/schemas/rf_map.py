"""RF Map DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
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
    # storage_url 이 s3:// 면 자동 발급한 presigned GET URL (TTL: RF_PRESIGNED_URL_EXPIRES_SECONDS).
    # 프론트는 이걸 <img src> 로 바로 사용. 로컬/HTTP URL 이면 None.
    url: Optional[str] = None
    bounds_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

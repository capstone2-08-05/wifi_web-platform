"""RF Run DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RfRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_version_id: UUID
    run_type: Optional[str] = None
    request_json: Optional[dict[str, Any]] = None


class RfRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    floor_id: UUID
    scene_version_id: UUID
    run_type: str
    status: str
    request_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RfRunCreatedResponse(RfRunResponse):
    job_id: UUID

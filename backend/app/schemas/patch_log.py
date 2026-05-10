"""Patch Log DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PatchLogResponse(BaseModel):
    id: UUID
    scene_version_id: UUID
    created_by: Optional[UUID] = None
    patch_type: str
    target_type: str
    target_id: UUID
    patch_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

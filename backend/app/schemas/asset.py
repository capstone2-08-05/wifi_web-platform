"""
Asset 도메인 DTO

"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssetResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    floor_id: Optional[UUID] = None
    uploaded_by: Optional[UUID] = None
    asset_type: str
    source_format: Optional[str] = None
    storage_url: str
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    metadata_json: Optional[dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime
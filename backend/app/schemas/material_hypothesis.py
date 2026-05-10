"""Material Hypothesis DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MaterialHypothesisResponse(BaseModel):
    id: UUID
    scene_version_id: UUID
    target_type: str
    target_id: UUID
    material_name: str
    confidence: Optional[Decimal] = None
    source_method: Optional[str] = None
    is_selected: bool
    evidence_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

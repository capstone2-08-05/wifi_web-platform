"""Material 도메인 DTO"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class MaterialResponse(BaseModel):
    id: UUID
    material_code: str
    material_name: str
    category: Optional[str] = None
    is_active: bool
    created_at: datetime


class MaterialRfProfileResponse(BaseModel):
    id: UUID
    material_id: UUID
    freq_ghz: Decimal
    permittivity: Decimal
    conductivity: Decimal
    penetration_loss_db: Decimal
    reference_thickness_m: Decimal
    profile_version: int
    is_default: bool

"""Material 조회 서비스"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.material import Material
from app.models.material_rf_profile import MaterialRfProfile
from app.schemas.material import MaterialResponse, MaterialRfProfileResponse


def list_materials(
    db: Session, is_active: Optional[bool] = None
) -> list[MaterialResponse]:
    stmt = select(Material)
    if is_active is not None:
        stmt = stmt.where(Material.is_active.is_(is_active))
    stmt = stmt.order_by(Material.material_code)
    rows = db.execute(stmt).scalars().all()
    return [MaterialResponse.model_validate(m, from_attributes=True) for m in rows]


def get_rf_profile(
    db: Session,
    material_id: UUID,
    freq_ghz: Optional[Decimal] = None,
) -> MaterialRfProfileResponse:
    material = db.execute(
        select(Material).where(Material.id == str(material_id))
    ).scalar_one_or_none()
    if material is None:
        raise AppError(
            ErrorCode.MATERIAL_NOT_FOUND,
            "Material not found.",
            status_code=404,
        )

    stmt = select(MaterialRfProfile).where(
        MaterialRfProfile.material_id == material.id
    )
    if freq_ghz is not None:
        stmt = stmt.where(MaterialRfProfile.freq_ghz == freq_ghz)
    else:
        stmt = stmt.where(MaterialRfProfile.is_default.is_(True))

    profile = db.execute(stmt).scalar_one_or_none()
    if profile is None:
        raise AppError(
            ErrorCode.MATERIAL_RF_PROFILE_NOT_FOUND,
            "RF profile not found for this material/frequency.",
            status_code=404,
        )
    return MaterialRfProfileResponse.model_validate(profile, from_attributes=True)

"""Material 라우터"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.material import MaterialResponse, MaterialRfProfileResponse
from app.services.catalog import material_service


router = APIRouter(prefix="/materials", tags=["materials"])


@router.get(
    "",
    response_model=list[MaterialResponse],
    summary="재질 목록",
)
def list_materials(
    is_active: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MaterialResponse]:
    return material_service.list_materials(db, is_active=is_active)


@router.get(
    "/{material_id}/rf-profile",
    response_model=MaterialRfProfileResponse,
    summary="재질의 RF 프로파일 (Sionna 입력용)",
)
def get_rf_profile(
    material_id: UUID = Path(...),
    freq_ghz: Optional[Decimal] = Query(
        default=None, description="미지정 시 default profile 반환"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialRfProfileResponse:
    return material_service.get_rf_profile(
        db, material_id=material_id, freq_ghz=freq_ghz
    )

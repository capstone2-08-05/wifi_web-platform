"""Material Hypothesis 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.catalog.material_hypothesis import MaterialHypothesisResponse
from app.services.catalog import material_hypothesis_service


wall_hypotheses_router = APIRouter(prefix="/walls", tags=["material-hypotheses"])
hypotheses_router = APIRouter(
    prefix="/material-hypotheses", tags=["material-hypotheses"]
)


@wall_hypotheses_router.get(
    "/{wall_id}/material-hypotheses",
    response_model=list[MaterialHypothesisResponse],
    summary="벽의 재질 후보 목록",
)
def list_hypotheses_for_wall(
    wall_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MaterialHypothesisResponse]:
    return material_hypothesis_service.list_hypotheses_for_wall(
        db, wall_id=wall_id, user=current_user
    )


@hypotheses_router.post(
    "/{hypothesis_id}/select",
    response_model=MaterialHypothesisResponse,
    summary="재질 후보 선택 (같은 wall 의 다른 후보 자동 false)",
)
def select_hypothesis(
    hypothesis_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialHypothesisResponse:
    return material_hypothesis_service.select_hypothesis(
        db, hypothesis_id=hypothesis_id, user=current_user
    )

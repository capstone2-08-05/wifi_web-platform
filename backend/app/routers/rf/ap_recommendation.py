"""AP 최적 위치 추천 라우터"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.rf.ap_recommendation import ApRecommendationRequest, ApRecommendationResponse
from app.services.rf import ap_recommendation_service

router = APIRouter(prefix="/ap-recommendation", tags=["ap-recommendation"])


@router.post(
    "",
    response_model=ApRecommendationResponse,
    summary="Grid Search 기반 AP 최적 위치 추천",
)
def recommend_ap(
    request: ApRecommendationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApRecommendationResponse:
    return ap_recommendation_service.recommend_ap_location(db, request, current_user)

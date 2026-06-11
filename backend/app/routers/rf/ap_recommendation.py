"""AP 최적 위치 추천 라우터"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.rf.ap_recommendation import (
    ApRecommendationRequest,
    ApRecommendationResponse,
    ApRecommendationRunResponse,
    ApRecommendationVerifyCandidateRequest,
    ApRecommendationVerifyCandidateResponse,
)
from app.services.rf import ap_recommendation_service

router = APIRouter(prefix="/ap-recommendation", tags=["ap-recommendation"])


@router.post(
    "",
    response_model=ApRecommendationResponse,
    summary="Grid Search 기반 AP 최적 위치 추천",
)
async def recommend_ap(
    request: ApRecommendationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApRecommendationResponse:
    return await ap_recommendation_service.recommend_ap_location(db, request, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ApRecommendationRunResponse],
    summary="도면 버전별 AP 추천 실행 이력 조회",
)
def list_ap_recommendation_runs(
    scene_version_id: UUID = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[ApRecommendationRunResponse]:
    return ap_recommendation_service.list_recommendation_runs(
        db,
        scene_version_id=scene_version_id,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{run_id}",
    response_model=ApRecommendationRunResponse,
    summary="AP 추천 실행 이력 단건 조회",
)
def get_ap_recommendation_run(
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApRecommendationRunResponse:
    return ap_recommendation_service.get_recommendation_run(
        db,
        run_id=run_id,
        current_user=current_user,
    )


@router.post(
    "/{run_id}/verify-candidate",
    response_model=ApRecommendationVerifyCandidateResponse,
    summary="선택한 추천 후보 1개에 대해 Sionna 검증 RF 실행 생성 (calibration 적용)",
)
async def verify_ap_recommendation_candidate(
    body: ApRecommendationVerifyCandidateRequest,
    run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApRecommendationVerifyCandidateResponse:
    return await ap_recommendation_service.verify_recommendation_candidate(
        db,
        run_id=run_id,
        candidate_rank=body.candidate_rank,
        current_user=current_user,
    )

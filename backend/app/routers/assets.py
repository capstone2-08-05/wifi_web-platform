"""
Asset 라우터 
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from pydantic import BaseModel

from app.schemas.asset import AssetResponse
from app.schemas.scene_draft import AnalyzeFromAssetRequest, AnalyzeFromAssetResponse
from app.services import asset_service, scene_draft_service


class AssetDownloadUrlResponse(BaseModel):
    url: str
    expires_in: int



floor_assets_router = APIRouter(prefix="/floors", tags=["assets"])
assets_router = APIRouter(prefix="/assets", tags=["assets"])


@floor_assets_router.post(
    "/{floor_id}/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="자산 업로드",
)
def upload_asset(
    floor_id: UUID = Path(..., description="자산을 추가할 층 ID"),
    file: UploadFile = File(..., description="png/jpg/jpeg/pdf"),
    asset_type: str = Form(..., description="floorplan / photo / document"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetResponse:
    asset = asset_service.create_asset(
        db=db,
        floor_id=floor_id,
        asset_type=asset_type,
        upload=file,
        user=current_user,
    )
    return AssetResponse.model_validate(asset)


@floor_assets_router.get(
    "/{floor_id}/assets",
    response_model=list[AssetResponse],
    summary="층의 자산 목록",
)
def list_assets(
    floor_id: UUID = Path(...),
    asset_type: Optional[str] = Query(
        None, description="필터: floorplan/photo/document"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssetResponse]:
    assets = asset_service.list_assets(
        db=db, floor_id=floor_id, user=current_user, asset_type=asset_type
    )
    return [AssetResponse.model_validate(a) for a in assets]

@assets_router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="자산 단건 조회",
)
def get_asset(
    asset_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetResponse:
    asset = asset_service.get_asset(db=db, asset_id=asset_id, user=current_user)
    return AssetResponse.model_validate(asset)


@assets_router.get(
    "/{asset_id}/download-url",
    response_model=AssetDownloadUrlResponse,
    summary="자산 파일 presigned GET URL 발급 (S3)",
)
def get_asset_download_url(
    asset_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetDownloadUrlResponse:
    url, expires_in = asset_service.get_asset_download_url(
        db=db, asset_id=asset_id, user=current_user
    )
    return AssetDownloadUrlResponse(url=url, expires_in=expires_in)


@assets_router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="자산 삭제 (DB row + S3 객체)",
)
def delete_asset(
    asset_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    asset_service.delete_asset(db=db, asset_id=asset_id, user=current_user)
    return None


@assets_router.post(
    "/{asset_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalyzeFromAssetResponse,
    summary="Asset 도면 분석 Job 등록 (비동기). job_id 받아서 GET /floorplan-jobs/{job_id} 폴링.",
)
async def analyze_asset(
    payload: AnalyzeFromAssetRequest,
    asset_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalyzeFromAssetResponse:
    return await scene_draft_service.analyze_from_asset(
        db=db,
        asset_id=asset_id,
        real_width_m=payload.real_width_m,
        current_user=current_user,
    )
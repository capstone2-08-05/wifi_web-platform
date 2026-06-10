"""RF Run 라우터"""
from __future__ import annotations

import re
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_internal_api_key
from app.core.settings import INTERNAL_API_KEY
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.rf.rf_map import RfMapCreate, RfMapResponse
from app.schemas.rf.rf_run import (
    RfRunCreate,
    RfRunCreatedResponse,
    RfRunResponse,
    RfRunUpdate,
)
from app.services import ai_api_client
from app.services.rf import rf_run_service


router = APIRouter(prefix="/rf-runs", tags=["rf-runs"])
floor_rf_runs_router = APIRouter(prefix="/floors", tags=["rf-runs"])
_SIONNA_RUN_ID_PATTERN = re.compile(r"^[0-9a-fA-F\-]{8,64}$")
_SIONNA_IMAGE_FILES = {
    "radiomap_heatmap.png",
    "radiomap_heatmap_annotated.png",
    "valid_mask.png",
    "geometry_overlay.png",
}


@floor_rf_runs_router.get(
    "/{floor_id}/rf-runs",
    response_model=PaginatedResponse[RfRunResponse],
    summary="층의 RF Run 목록 (created_at desc, status 필터, 페이지네이션)",
)
def list_floor_rf_runs(
    floor_id: UUID = Path(...),
    status: str | None = Query(default=None, description="queued|running|completed|failed 등"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[RfRunResponse]:
    return rf_run_service.list_by_floor(
        db, floor_id=floor_id, user=current_user, page=page, page_size=page_size, status=status
    )


@router.post(
    "",
    response_model=RfRunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="RF 시뮬레이션 Job 등록 (access_points + simulation 주면 SageMaker async invoke). job_id 받아서 GET /rf-jobs/{job_id} 로 폴링.",
)
async def create_rf_run(
    payload: RfRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunCreatedResponse:
    return await rf_run_service.create_rf_run(db, payload=payload, user=current_user)


@router.delete(
    "/{rf_run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="RF Run 삭제",
)
def delete_rf_run(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    rf_run_service.delete_rf_run(db, rf_run_id=rf_run_id, user=current_user)


@router.get(
    "/sionna-images/{sionna_run_id}.png",
    summary="Proxy Sionna heatmap image through the web backend.",
)
def proxy_sionna_heatmap_image(sionna_run_id: str) -> Response:
    return _proxy_sionna_image(sionna_run_id, "radiomap_heatmap.png")


@router.get(
    "/sionna-images/{sionna_run_id}/{filename}",
    summary="Proxy a Sionna artifact image through the web backend.",
)
def proxy_sionna_artifact_image(sionna_run_id: str, filename: str) -> Response:
    return _proxy_sionna_image(sionna_run_id, filename)


@router.get(
    "/{rf_run_id}",
    response_model=RfRunResponse,
    summary="RF 실행 상태/결과 조회",
)
def get_rf_run(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RfRunResponse:
    return rf_run_service.get_rf_run(db, rf_run_id=rf_run_id, user=current_user)


@router.get(
    "/{rf_run_id}/maps",
    response_model=list[RfMapResponse],
    summary="생성된 전파 맵 목록",
)
def list_rf_maps(
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RfMapResponse]:
    return rf_run_service.list_maps(db, rf_run_id=rf_run_id, user=current_user)


def _proxy_sionna_image(sionna_run_id: str, filename: str) -> Response:
    if not _SIONNA_RUN_ID_PATTERN.match(sionna_run_id):
        raise HTTPException(status_code=400, detail="invalid sionna_run_id format")
    if filename not in _SIONNA_IMAGE_FILES:
        raise HTTPException(status_code=404, detail=f"file not allowed: {filename}")

    base_path = f"{ai_api_client._base_url()}/internal/sionna/images/{sionna_run_id}"
    url = f"{base_path}.png" if filename == "radiomap_heatmap.png" else f"{base_path}/{filename}"
    headers = {"X-Internal-API-Key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}

    try:
        resp = httpx.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        if status_code in {400, 404}:
            raise HTTPException(status_code=status_code, detail="sionna image not found") from exc
        raise HTTPException(status_code=502, detail="failed to fetch sionna image") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="failed to fetch sionna image") from exc

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
    )


# ---------------------------------------------------------------------------
# 시스템 호출용 (AI 서버 → 백엔드)
# ---------------------------------------------------------------------------
@router.patch(
    "/{rf_run_id}",
    response_model=RfRunResponse,
    summary="[시스템] RF Run 상태/메트릭 갱신 (AI 서버용)",
    dependencies=[Depends(verify_internal_api_key)],
)
def update_rf_run(
    payload: RfRunUpdate,
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> RfRunResponse:
    return rf_run_service.update_rf_run(
        db, rf_run_id=rf_run_id, payload=payload
    )


@router.post(
    "/{rf_run_id}/maps",
    response_model=RfMapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[시스템] RF Map 결과 저장 (AI 서버용)",
    dependencies=[Depends(verify_internal_api_key)],
)
def create_rf_map(
    payload: RfMapCreate,
    rf_run_id: UUID = Path(...),
    db: Session = Depends(get_db),
) -> RfMapResponse:
    return rf_run_service.create_rf_map(
        db, rf_run_id=rf_run_id, payload=payload
    )

"""
Floor 라우터
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.floor import (
    FloorCreateRequest,
    FloorResponse,
    FloorUpdateRequest,
)
from app.services import floor_service

router = APIRouter(tags=["floors"])


# ============================================
# Project-scoped (생성, 목록)
# ============================================
@router.post(
    "/projects/{project_id}/floors",
    response_model=FloorResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="층 생성",
)
def create_floor(
    project_id: str,
    payload: FloorCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FloorResponse:
    return floor_service.create_floor(db, project_id, payload, current_user)


@router.get(
    "/projects/{project_id}/floors",
    summary="프로젝트의 층 목록",
)
def list_floors_by_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    items = floor_service.list_floors_by_project(db, project_id, current_user)
    # by_alias=True로 명시적 직렬화
    return {"items": [item.model_dump(by_alias=True, mode="json") for item in items]}


# ============================================
# Floor-scoped (단건)
# ============================================
@router.get(
    "/floors/{floor_id}",
    response_model=FloorResponse,
     response_model_by_alias=True,
    summary="층 단건 조회",
)
def get_floor(
    floor_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FloorResponse:
    return floor_service.get_floor(db, floor_id, current_user)


@router.patch(
    "/floors/{floor_id}",
    response_model=FloorResponse,
     response_model_by_alias=True,
    summary="층 부분 수정",
)
def update_floor(
    floor_id: str,
    payload: FloorUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FloorResponse:
    return floor_service.update_floor(db, floor_id, payload, current_user)


@router.delete(
    "/floors/{floor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="층 삭제",
)
def delete_floor(
    floor_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    floor_service.delete_floor(db, floor_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
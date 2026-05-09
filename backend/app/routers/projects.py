"""
Project 라우터
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="프로젝트 생성",
)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    return project_service.create_project(db, payload, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    summary="프로젝트 목록 조회 (본인 소유)",
)
def list_projects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, pattern="^(active|archived)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[ProjectResponse]:
    return project_service.list_projects(
        db, current_user, page=page, page_size=page_size, status=status
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="프로젝트 단건 조회",
)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    return project_service.get_project(db, project_id, current_user)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="프로젝트 부분 수정",
)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    return project_service.update_project(db, project_id, payload, current_user)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="프로젝트 삭제",
)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    project_service.delete_project(db, project_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
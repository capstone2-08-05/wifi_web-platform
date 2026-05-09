"""
인증 라우터: /auth/signup, /auth/login, /auth/me
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
)
def signup(
    payload: SignupRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    return auth_service.signup(db, payload)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="로그인",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    return auth_service.login(db, payload)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="현재 로그인한 사용자 정보",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)
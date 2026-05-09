"""
인증 서비스: 회원가입, 로그인, 토큰 발급
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.settings import JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)


def signup(db: Session, payload: SignupRequest) -> UserResponse:
  
    normalized_email = payload.email.strip().lower()

    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing is not None:
        raise AppError(
            ErrorCode.EMAIL_ALREADY_EXISTS,
            "An account with this email already exists.",
            status_code=409,
        )

    user = User(
        email=normalized_email,
        password=hash_password(payload.password),
        name=payload.name.strip(),
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.EMAIL_ALREADY_EXISTS,
            "An account with this email already exists.",
            status_code=409,
        ) from exc

    return UserResponse.model_validate(user)


def login(db: Session, payload: LoginRequest) -> TokenResponse:
   
    normalized_email = payload.email.strip().lower()

    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None or not verify_password(payload.password, user.password):
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password.",
            status_code=401,
        )

    return _build_token_response(user)


def _build_token_response(user: User) -> TokenResponse:
    access_token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email},
    )
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )
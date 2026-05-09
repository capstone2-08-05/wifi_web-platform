"""
공통 의존성: 인증된 사용자 추출
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User


def _extract_bearer_token(request: Request) -> str:
    """Authorization 헤더에서 Bearer 토큰 꺼내기"""
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            "Missing Authorization header.",
            status_code=401,
        )

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            "Invalid Authorization header format. Expected 'Bearer <token>'.",
            status_code=401,
        )

    return parts[1]


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    인증된 사용자를 반환하는 의존성.
    - Authorization: Bearer <token> 헤더 필수
    - 토큰 만료/위조 시 401
    - 유저가 DB에서 사라졌으면 401
    """
    token = _extract_bearer_token(request)
    payload = decode_access_token(token)

    user_id = payload.get("sub")
    if not user_id:
        raise AppError(
            ErrorCode.INVALID_TOKEN,
            "Token does not contain a subject.",
            status_code=401,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            "User in token no longer exists.",
            status_code=401,
        )

    return user
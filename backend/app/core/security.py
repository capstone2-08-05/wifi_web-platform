"""
보안 유틸리티: 비밀번호 해싱, JWT 발급/검증
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)

# ============================================
# Password Hashing
# ============================================
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


# ============================================
# JWT
# ============================================
def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
  
    expire_minutes = expires_minutes if expires_minutes is not None else JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire_at,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
   
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            ErrorCode.TOKEN_EXPIRED,
            "Access token has expired.",
            status_code=401,
        ) from exc
    except JWTError as exc:
        raise AppError(
            ErrorCode.INVALID_TOKEN,
            "Invalid access token.",
            status_code=401,
        ) from exc

    if payload.get("type") != "access":
        raise AppError(
            ErrorCode.INVALID_TOKEN,
            "Invalid token type.",
            status_code=401,
        )

    return payload
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        raise AppError(
            ErrorCode.DB_CONNECTION_FAILED,
            f"Database connection failed: {exc}",
            503,
        ) from exc

from fastapi import APIRouter
from sqlalchemy import create_engine, text

from app.core.settings import database_url

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> dict:
    engine = create_engine(database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        return {"status": "error", "db": "disconnected", "detail": str(exc)}
    finally:
        engine.dispose()

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import (
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT_SECONDS,
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    # 커넥션을 못 얻으면 무한 대기 대신 timeout → 풀 고갈이 hang 이 아니라 명시적 에러로 보임.
    pool_timeout=DB_POOL_TIMEOUT_SECONDS,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

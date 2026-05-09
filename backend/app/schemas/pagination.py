"""
페이지네이션 공통 스키마
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationQuery(BaseModel):
    """목록 조회 쿼리 파라미터"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel, Generic[T]):
    """목록 응답: items + 페이지 정보"""
    items: list[T]
    page: int
    page_size: int
    total: int
    
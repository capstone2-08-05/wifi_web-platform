"""
Project 도메인 DTO
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ============================================
# Request DTO
# ============================================
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdateRequest(BaseModel):
    """모두 optional — 부분 수정"""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


# ============================================
# Response DTO
# ============================================
class ProjectResponse(BaseModel):
    id: str
    owner_user_id: str
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
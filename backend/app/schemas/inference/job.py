"""Job DTO"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.enums import normalize_job_status


class JobResponse(BaseModel):
    id: UUID
    project_id: UUID
    floor_id: Optional[UUID] = None
    job_type: str
    status: str
    input_json: dict[str, Any] = Field(default_factory=dict)
    result_json: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        """내부 status(running/done/failed/queued/completed) → API 표기로 통일.

        floorplan/rf/legacy 잡이 제각각 쓰는 종료 상태를 API 경계에서
        pending/running/succeeded/failed 로 normalize. DB 값은 그대로 둠.
        """
        if isinstance(v, str):
            return normalize_job_status(v)
        return v

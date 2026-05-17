from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (Index("idx_floors_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    floor_index: Mapped[int] = mapped_column(Integer(), nullable=False, server_default=text("0"))
    default_ceiling_height_m: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, server_default=text("2.4")
    )
    # 공간 메타데이터: bounds_m, scale_m_per_px, coordinate_system 등.
    # 도면 asset 과 분리해서 보관 — asset 이 교체되어도 측정 좌표계가 흔들리지 않음.
    # 첫 도면 분석 완료 시 floorplan_job_service 가 seed 한다.
    spatial_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project = relationship("Project", back_populates="floors")
    assets = relationship("Asset", back_populates="floor")
    scene_drafts = relationship("SceneDraft", back_populates="floor")

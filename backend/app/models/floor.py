from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project = relationship("Project", back_populates="floors")
    assets = relationship("Asset", back_populates="floor")
    scene_drafts = relationship("SceneDraft", back_populates="floor")

from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DraftOpening(Base):
    __tablename__ = "draft_openings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scene_draft_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scene_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    wall_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("draft_walls.id", ondelete="SET NULL"),
        nullable=True,
    )
    opening_type: Mapped[str] = mapped_column(String(20), nullable=False)
    width_m: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    height_m: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    sill_height_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    line_geom = mapped_column(Geometry("LINESTRING", srid=0), nullable=True)
    polygon_geom = mapped_column(Geometry("POLYGON", srid=0), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    scene_draft = relationship("SceneDraft", back_populates="draft_openings")
    wall = relationship("DraftWall", back_populates="draft_openings")

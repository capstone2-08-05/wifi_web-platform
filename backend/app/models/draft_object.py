from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DraftObject(Base):
    __tablename__ = "draft_objects"

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
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    point_geom = mapped_column(Geometry("POINT", srid=0), nullable=True)
    z_m: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True, server_default=text("0")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    scene_draft = relationship("SceneDraft", back_populates="draft_objects")

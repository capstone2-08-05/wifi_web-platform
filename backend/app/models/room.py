from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scene_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scene_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    room_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    room_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    polygon_geom = mapped_column(Geometry("POLYGON", srid=0), nullable=True)
    centroid_geom = mapped_column(Geometry("POINT", srid=0), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    scene_version = relationship("SceneVersion", back_populates="rooms")

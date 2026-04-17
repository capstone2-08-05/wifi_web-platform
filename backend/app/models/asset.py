from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (Index("idx_assets_project_floor", "project_id", "floor_id"),)

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
    floor_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("floors.id", ondelete="SET NULL"),
        nullable=True,
    )
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_url: Mapped[str] = mapped_column(Text(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project = relationship("Project", back_populates="assets")
    floor = relationship("Floor", back_populates="assets")
    source_scene_drafts = relationship("SceneDraft", back_populates="source_asset")

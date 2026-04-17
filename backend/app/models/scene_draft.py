from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SceneDraft(Base):
    __tablename__ = "scene_drafts"
    __table_args__ = (Index("idx_scene_drafts_project_floor", "project_id", "floor_id"),)

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
    floor_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("floors.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'floorplan_image'")
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'draft'"))
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project = relationship("Project", back_populates="scene_drafts")
    floor = relationship("Floor", back_populates="scene_drafts")
    source_asset = relationship("Asset", back_populates="source_scene_drafts")
    draft_rooms = relationship("DraftRoom", back_populates="scene_draft")
    draft_walls = relationship("DraftWall", back_populates="scene_draft")
    draft_openings = relationship("DraftOpening", back_populates="scene_draft")
    draft_objects = relationship("DraftObject", back_populates="scene_draft")

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SceneVersion(Base):
    __tablename__ = "scene_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "floor_id", "version_no",
            name="uq_scene_versions_project_floor_version",
        ),
        Index("idx_scene_versions_project_floor", "project_id", "floor_id"),
    )

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
    scene_draft_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scene_drafts.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("false")
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
    render_scene_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    rf_scene_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    artifacts_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    rooms = relationship(
        "Room",
        back_populates="scene_version",
        cascade="all, delete",
        passive_deletes=True,
    )
    walls = relationship(
        "Wall",
        back_populates="scene_version",
        cascade="all, delete",
        passive_deletes=True,
    )
    openings = relationship(
        "Opening",
        back_populates="scene_version",
        cascade="all, delete",
        passive_deletes=True,
    )
    objects = relationship(
        "SceneObject",
        back_populates="scene_version",
        cascade="all, delete",
        passive_deletes=True,
    )
    patch_logs = relationship(
        "PatchLog",
        back_populates="scene_version",
        cascade="all, delete",
        passive_deletes=True,
    )

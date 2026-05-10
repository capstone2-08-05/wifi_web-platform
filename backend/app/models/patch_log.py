from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PatchLog(Base):
    __tablename__ = "patch_logs"
    __table_args__ = (
        Index("idx_patch_logs_version_target", "scene_version_id", "target_type"),
    )

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
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    patch_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patch_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    scene_version = relationship("SceneVersion", back_populates="patch_logs")

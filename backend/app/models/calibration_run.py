from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CalibrationRun(Base):
    __tablename__ = "calibration_runs"
    __table_args__ = (
        Index("idx_calibration_runs_scene_version", "scene_version_id"),
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
    scene_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scene_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    rf_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("rf_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    measurement_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'queued'")
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    parameter_updates = relationship(
        "ParameterUpdate",
        back_populates="calibration_run",
        cascade="all, delete",
        passive_deletes=True,
    )

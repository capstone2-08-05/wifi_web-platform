from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeasurementLink(Base):
    __tablename__ = "measurement_links"
    __table_args__ = (
        Index("idx_measurement_links_floor_id", "floor_id"),
        Index("idx_measurement_links_token", "token", unique=True),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    token: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
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
    scene_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scene_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    asset_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'rssi_measurement'")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project = relationship("Project")
    floor = relationship("Floor")
    asset = relationship("Asset")

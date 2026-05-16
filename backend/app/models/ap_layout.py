from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApLayout(Base):
    __tablename__ = "ap_layouts"
    __table_args__ = (
        Index("idx_ap_layouts_rf_run", "rf_run_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rf_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("rf_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ap_name: Mapped[str] = mapped_column(String(60), nullable=False)
    vendor_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    point_geom = mapped_column(Geometry("POINT", srid=0), nullable=False)
    z_m: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    azimuth_deg: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("0")
    )
    tilt_deg: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("0")
    )
    power_dbm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    channel_info_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

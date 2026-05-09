from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeasurementPoint(Base):
    __tablename__ = "measurement_points"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    point_geom = mapped_column(Geometry("POINT", srid=0), nullable=False)
    z_m: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True, server_default=text("1.2")
    )
    rssi_dbm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    sinr_db: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    throughput_mbps: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    ap_bssid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    batch_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    client_point_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ap_ssid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    channel: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    frequency_mhz: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    timestamp_at_point: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ar_tracking_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ar_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    step_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    session = relationship("MeasurementSession", back_populates="points")

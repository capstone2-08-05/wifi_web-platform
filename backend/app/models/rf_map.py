from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RfMap(Base):
    __tablename__ = "rf_maps"

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
    map_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_cm: Mapped[int] = mapped_column(Integer(), nullable=False)
    storage_url: Mapped[str] = mapped_column(Text(), nullable=False)
    bounds_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    rf_run = relationship("RfRun", back_populates="rf_maps")

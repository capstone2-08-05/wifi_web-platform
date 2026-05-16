from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ParameterUpdate(Base):
    __tablename__ = "parameter_updates"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    calibration_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("calibration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    calibration_run = relationship(
        "CalibrationRun", back_populates="parameter_updates"
    )

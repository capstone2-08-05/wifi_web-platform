from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MaterialRfProfile(Base):
    __tablename__ = "material_rf_profiles"
    __table_args__ = (
        Index(
            "idx_material_rf_profiles_material_freq",
            "material_id",
            "freq_ghz",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    material_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    freq_ghz: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    permittivity: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    conductivity: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    penetration_loss_db: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), nullable=False
    )
    reference_thickness_m: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False
    )
    profile_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default=text("1")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    material = relationship("Material", back_populates="rf_profiles")

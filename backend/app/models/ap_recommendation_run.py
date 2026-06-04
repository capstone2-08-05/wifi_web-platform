from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ApRecommendationRun(Base):
    __tablename__ = "ap_recommendation_runs"
    __table_args__ = (
        Index("idx_ap_recommendation_runs_scene_version", "scene_version_id"),
        Index("idx_ap_recommendation_runs_floor", "floor_id"),
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
    calibration_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("calibration_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'completed'")
    )
    request_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    input_areas_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    existing_aps_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    calibration_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    score_weights_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    candidates_evaluated: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default=text("0")
    )
    eval_points_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    weighted_eval_points_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    items = relationship(
        "ApRecommendationItem",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ApRecommendationItem.rank",
    )


class ApRecommendationItem(Base):
    __tablename__ = "ap_recommendation_items"
    __table_args__ = (
        Index("idx_ap_recommendation_items_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("ap_recommendation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer(), nullable=False)
    recommended_x: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    recommended_y: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prediction_points_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    run = relationship("ApRecommendationRun", back_populates="items")

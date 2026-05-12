"""measurement api: links + extend sessions/points

Revision ID: 20260509_0003
Revises: 20260509_0002
Create Date: 2026-05-09 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260509_0003"
down_revision: Union[str, Sequence[str], None] = "20260509_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "measurement_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token", sa.String(length=80), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "floor_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("floors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("scene_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "purpose",
            sa.String(length=40),
            nullable=False,
            server_default="rssi_measurement",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_measurement_links_floor_id", "measurement_links", ["floor_id"])
    op.create_index(
        "idx_measurement_links_token", "measurement_links", ["token"], unique=True
    )

    op.add_column(
        "measurement_sessions",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="in_progress",
        ),
    )
    op.add_column(
        "measurement_sessions",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "measurement_sessions",
        sa.Column(
            "calibration_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column(
        "measurement_sessions",
        "measurement_type",
        server_default="rssi",
    )

    op.add_column(
        "measurement_points",
        sa.Column("batch_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("client_point_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("ap_ssid", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("channel", sa.Integer(), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("frequency_mhz", sa.Integer(), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("timestamp_at_point", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("ar_tracking_state", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("ar_confidence", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "measurement_points",
        sa.Column("step_index", sa.Integer(), nullable=True),
    )
    op.create_index(
        "uq_measurement_points_session_client_point",
        "measurement_points",
        ["session_id", "client_point_id"],
        unique=True,
        postgresql_where=sa.text("client_point_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_measurement_points_session_client_point", table_name="measurement_points"
    )
    for col in [
        "step_index",
        "ar_confidence",
        "ar_tracking_state",
        "timestamp_at_point",
        "frequency_mhz",
        "channel",
        "ap_ssid",
        "client_point_id",
        "batch_id",
    ]:
        op.drop_column("measurement_points", col)

    op.alter_column(
        "measurement_sessions",
        "measurement_type",
        server_default="smartphone_app",
    )
    for col in ["calibration_json", "completed_at", "status"]:
        op.drop_column("measurement_sessions", col)

    op.drop_index("idx_measurement_links_token", table_name="measurement_links")
    op.drop_index("idx_measurement_links_floor_id", table_name="measurement_links")
    op.drop_table("measurement_links")

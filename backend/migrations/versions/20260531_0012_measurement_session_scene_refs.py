"""Store scene/asset refs on measurement sessions."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260531_0012"
down_revision = "20260529_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "measurement_sessions",
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "measurement_sessions",
        sa.Column("asset_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_measurement_sessions_scene_version_id",
        "measurement_sessions",
        "scene_versions",
        ["scene_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_measurement_sessions_asset_id",
        "measurement_sessions",
        "assets",
        ["asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_measurement_sessions_scene_version_id",
        "measurement_sessions",
        ["scene_version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_measurement_sessions_scene_version_id", table_name="measurement_sessions")
    op.drop_constraint(
        "fk_measurement_sessions_asset_id",
        "measurement_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_measurement_sessions_scene_version_id",
        "measurement_sessions",
        type_="foreignkey",
    )
    op.drop_column("measurement_sessions", "asset_id")
    op.drop_column("measurement_sessions", "scene_version_id")

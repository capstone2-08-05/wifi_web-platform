"""store AP recommendation run history

Revision ID: 20260604_0013
Revises: 20260531_0012
Create Date: 2026-06-04 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260604_0013"
down_revision: Union[str, Sequence[str], None] = "20260531_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ap_recommendation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
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
            sa.ForeignKey("scene_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calibration_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("calibration_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'completed'"),
        ),
        sa.Column(
            "request_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "input_areas_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "existing_aps_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "calibration_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "score_weights_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "candidates_evaluated",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("eval_points_count", sa.Integer(), nullable=True),
        sa.Column("weighted_eval_points_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_ap_recommendation_runs_scene_version",
        "ap_recommendation_runs",
        ["scene_version_id"],
    )
    op.create_index(
        "idx_ap_recommendation_runs_floor",
        "ap_recommendation_runs",
        ["floor_id"],
    )

    op.create_table(
        "ap_recommendation_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ap_recommendation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("recommended_x", sa.Numeric(10, 3), nullable=False),
        sa.Column("recommended_y", sa.Numeric(10, 3), nullable=False),
        sa.Column("score", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "metrics_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "prediction_points_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_ap_recommendation_items_run",
        "ap_recommendation_items",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_ap_recommendation_items_run", table_name="ap_recommendation_items")
    op.drop_table("ap_recommendation_items")
    op.drop_index("idx_ap_recommendation_runs_floor", table_name="ap_recommendation_runs")
    op.drop_index(
        "idx_ap_recommendation_runs_scene_version",
        table_name="ap_recommendation_runs",
    )
    op.drop_table("ap_recommendation_runs")

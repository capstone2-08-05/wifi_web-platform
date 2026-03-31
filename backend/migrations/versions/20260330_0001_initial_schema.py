"""initial schema

Revision ID: 20260330_0001
Revises:
Create Date: 2026-03-30 10:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260330_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "floors",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("floor_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_ceiling_height_m", sa.Numeric(6, 3), nullable=False, server_default="2.4"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_floors_project_id", "floors", ["project_id"])

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_assets_project_floor", "assets", ["project_id", "floor_id"])

    op.create_table(
        "scene_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_mode", sa.String(length=30), nullable=False, server_default="floorplan_image"),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_scene_drafts_project_floor", "scene_drafts", ["project_id", "floor_id"])

    op.create_table(
        "draft_rooms",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_draft_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_name", sa.String(length=80), nullable=True),
        sa.Column("room_type", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("centroid_geom", Geometry("POINT", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "draft_walls",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_draft_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wall_role", sa.String(length=20), nullable=False, server_default="inner"),
        sa.Column("thickness_m", sa.Numeric(6, 3), nullable=False, server_default="0.18"),
        sa.Column("height_m", sa.Numeric(6, 3), nullable=True),
        sa.Column("material_label", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("centerline_geom", Geometry("LINESTRING", srid=0), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "draft_openings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_draft_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wall_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("draft_walls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opening_type", sa.String(length=20), nullable=False),
        sa.Column("width_m", sa.Numeric(6, 3), nullable=False),
        sa.Column("height_m", sa.Numeric(6, 3), nullable=False),
        sa.Column("sill_height_m", sa.Numeric(6, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("line_geom", Geometry("LINESTRING", srid=0), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "draft_objects",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_draft_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=True),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=True, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "scene_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_draft_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_drafts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_mode", sa.String(length=30), nullable=False, server_default="floorplan_image"),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("render_scene_url", sa.Text(), nullable=True),
        sa.Column("rf_scene_url", sa.Text(), nullable=True),
        sa.Column("artifacts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "floor_id", "version_no", name="uq_scene_versions_project_floor_version"),
    )
    op.create_index("idx_scene_versions_project_floor", "scene_versions", ["project_id", "floor_id"])

    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_name", sa.String(length=80), nullable=True),
        sa.Column("room_type", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("centroid_geom", Geometry("POINT", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_rooms_polygon_geom", "rooms", ["polygon_geom"], postgresql_using="gist")

    op.create_table(
        "walls",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wall_role", sa.String(length=20), nullable=False, server_default="inner"),
        sa.Column("thickness_m", sa.Numeric(6, 3), nullable=False, server_default="0.18"),
        sa.Column("height_m", sa.Numeric(6, 3), nullable=True),
        sa.Column("material_label", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("centerline_geom", Geometry("LINESTRING", srid=0), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_walls_centerline_geom", "walls", ["centerline_geom"], postgresql_using="gist")

    op.create_table(
        "openings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wall_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("walls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opening_type", sa.String(length=20), nullable=False),
        sa.Column("width_m", sa.Numeric(6, 3), nullable=False),
        sa.Column("height_m", sa.Numeric(6, 3), nullable=False),
        sa.Column("sill_height_m", sa.Numeric(6, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("line_geom", Geometry("LINESTRING", srid=0), nullable=True),
        sa.Column("polygon_geom", Geometry("POLYGON", srid=0), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_openings_polygon_geom", "openings", ["polygon_geom"], postgresql_using="gist")

    op.create_table(
        "objects",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=True),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=True, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "measurement_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("measurement_type", sa.String(length=30), nullable=False, server_default="smartphone_app"),
        sa.Column("device_info_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "measurement_points",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=False),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=True, server_default="1.2"),
        sa.Column("rssi_dbm", sa.Numeric(6, 2), nullable=True),
        sa.Column("sinr_db", sa.Numeric(6, 2), nullable=True),
        sa.Column("latency_ms", sa.Numeric(8, 2), nullable=True),
        sa.Column("throughput_mbps", sa.Numeric(10, 3), nullable=True),
        sa.Column("ap_bssid", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_measurement_points_session", "measurement_points", ["session_id"])
    op.create_index("idx_measurement_points_geom", "measurement_points", ["point_geom"], postgresql_using="gist")

    op.create_table(
        "rf_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_type", sa.String(length=30), nullable=False, server_default="quick_preview"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_rf_runs_scene_version", "rf_runs", ["scene_version_id"])

    op.create_table(
        "ap_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=False),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=True, server_default="2.2"),
        sa.Column("score", sa.Numeric(6, 4), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_ap_candidates_geom", "ap_candidates", ["point_geom"], postgresql_using="gist")

    op.create_table(
        "ap_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layout_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ap_layout_points",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ap_layout_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("ap_layouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ap_label", sa.String(length=80), nullable=True),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=False),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=True, server_default="2.2"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "calibration_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("floor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("floors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rf_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("rf_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "material_hypotheses",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("material_name", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "parameter_updates",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("calibration_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("calibration_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("parameter_name", sa.String(length=80), nullable=False),
        sa.Column("old_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "rf_maps",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rf_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("rf_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("map_type", sa.String(length=30), nullable=False),
        sa.Column("resolution_cm", sa.Integer(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("bounds_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    for table in [
        "rf_maps",
        "ap_layout_points",
        "ap_layouts",
        "ap_candidates",
        "parameter_updates",
        "material_hypotheses",
        "calibration_runs",
        "rf_runs",
        "measurement_points",
        "measurement_sessions",
        "draft_objects",
        "draft_openings",
        "draft_walls",
        "draft_rooms",
        "jobs",
        "objects",
        "openings",
        "walls",
        "rooms",
        "scene_versions",
        "scene_drafts",
        "assets",
        "floors",
        "projects",
    ]:
        op.drop_table(table)

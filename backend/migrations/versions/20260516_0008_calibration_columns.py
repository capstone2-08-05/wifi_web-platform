"""calibration_runs 보강: measurement_session_id + finished_at + error_message (§11)

기존 initial_schema 의 calibration_runs 는 measurement 연결이 없었고 Job 표준
컬럼(finished_at / error_message) 도 부족 → §11 API 구현 위해 추가.

Revision ID: 20260516_0008
Revises: 20260516_0007
Create Date: 2026-05-16 00:00:00


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260516_0008"
down_revision: Union[str, Sequence[str], None] = "20260516_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calibration_runs",
        sa.Column(
            "measurement_session_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_calibration_runs_scene_version",
        "calibration_runs",
        ["scene_version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_calibration_runs_scene_version", table_name="calibration_runs")
    op.drop_column("calibration_runs", "error_message")
    op.drop_column("calibration_runs", "finished_at")
    op.drop_column("calibration_runs", "measurement_session_id")

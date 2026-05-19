"""floors.spatial_meta JSONB 추가 — 측정 좌표계/스케일을 asset 과 분리

기존: bounds/scale/coordinate_system 은 asset.metadata_json (도면 이미지) 에서 파생.
   → 도면 asset 이 교체되면 spatial 정의도 같이 흔들리고, asset 이 아예 없으면
     bounds 가 비어 측정 검증이 무력화됨.

변경: floor 단위에 spatial_meta JSONB 컬럼 추가. 첫 도면 분석 시 자동 seed.
   → asset 교체에도 spatial 보존, asset 미존재 시에도 spatial 수동 입력 가능.

예시 spatial_meta 형태:
  {
    "bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 50.0, "max_y": 30.0},
    "scale_m_per_px": 0.0234,
    "coordinate_system": {
      "unit": "meter",
      "origin": "top_left",
      "x_axis": "right",
      "y_axis": "down",
      "z_axis": "up",
      "heading_zero_axis": "x",
      "heading_positive_direction": "cw"
    }
  }

Revision ID: 20260517_0009
Revises: 20260516_0008
Create Date: 2026-05-17 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260517_0009"
down_revision: Union[str, Sequence[str], None] = "20260516_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "floors",
        sa.Column(
            "spatial_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("floors", "spatial_meta")

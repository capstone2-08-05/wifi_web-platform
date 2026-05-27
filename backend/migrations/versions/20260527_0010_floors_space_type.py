"""floors.space_type 추가 — calibration prior 의 source of truth 를 Floor 단위로 통일.

기존: space_type 이 CalibrationRunCreate.space_type 으로 request 마다 전달됨 → 사용자가
   보정마다 같은 값 반복 선택해야 하고, 시뮬 페이지에선 모르는 정보였음.

변경: Floor 에 space_type 컬럼 추가. 사용자가 floor 단위로 한 번 정하면 calibration 이
   자동으로 그 값 사용. 미지정 시 'unknown' (기존 fallback 과 동일).

Revision ID: 20260527_0010
Revises: 20260517_0009
Create Date: 2026-05-27 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260527_0010"
down_revision: Union[str, Sequence[str], None] = "20260517_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "floors",
        sa.Column(
            "space_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("floors", "space_type")

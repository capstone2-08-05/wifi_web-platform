"""rebuild ap_layouts per spec §14.3/14.4 (AP recommendation 제외)

기존 initial_schema 의 ap_layouts / ap_candidates / ap_layout_points 는
명세와 구조가 달라 (layout=컨테이너, rf_run 미연결) 한 번도 사용 안 됨.
명세 §14.3/14.4 (layout=AP 개별, rf_run 연결) 로 재구성.

명세 §14.1/14.2 의 ap_candidates (자동 추천) 는 본 프로젝트 워크플로
(사용자 수동 배치 → 시뮬 → 보고 옮기기) 에 맞지 않아 제외.

Revision ID: 20260516_0007
Revises: 20260511_0006
Create Date: 2026-05-16 00:00:00


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql


revision: str = "20260516_0007"
down_revision: Union[str, Sequence[str], None] = "20260511_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 기존 더미 테이블 정리 (한 번도 안 쓰임) ─────────────────────────
    op.execute("DROP TABLE IF EXISTS ap_layout_points CASCADE")
    op.execute("DROP TABLE IF EXISTS ap_layouts CASCADE")
    op.execute("DROP TABLE IF EXISTS ap_candidates CASCADE")

    # ── §14.3/14.4 ap_layouts (AP 개별 배치) ──────────────────────────
    op.create_table(
        "ap_layouts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "rf_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("rf_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ap_name", sa.String(length=60), nullable=False),
        sa.Column("vendor_model", sa.String(length=60), nullable=True),
        sa.Column("point_geom", Geometry("POINT", srid=0), nullable=False),
        sa.Column("z_m", sa.Numeric(6, 3), nullable=False),
        sa.Column(
            "azimuth_deg",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tilt_deg",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("power_dbm", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "channel_info_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_ap_layouts_rf_run", "ap_layouts", ["rf_run_id"])


def downgrade() -> None:
    op.drop_index("idx_ap_layouts_rf_run", table_name="ap_layouts")
    op.drop_table("ap_layouts")
    # 기존 더미 테이블 복원은 하지 않음 (사용 안 됨)

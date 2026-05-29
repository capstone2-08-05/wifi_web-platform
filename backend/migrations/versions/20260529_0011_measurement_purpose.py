"""add measurement purpose fields

Revision ID: 20260529_0011
Revises: 20260527_0010
Create Date: 2026-05-29 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260529_0011"
down_revision: Union[str, Sequence[str], None] = "20260527_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "measurement_sessions",
        sa.Column(
            "measurement_purpose",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column(
        "measurement_points",
        sa.Column("measurement_purpose", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("measurement_points", "measurement_purpose")
    op.drop_column("measurement_sessions", "measurement_purpose")

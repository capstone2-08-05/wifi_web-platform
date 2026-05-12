"""add source_format, mime_type, file_size_bytes to assets; widen asset_type

Revision ID: 20260510_0004
Revises: 20260509_0003
Create Date: 2026-05-10 12:00:00


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260510_0004"
down_revision: Union[str, Sequence[str], None] = "20260509_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("source_format", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("mime_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
    )

    op.alter_column(
        "assets",
        "asset_type",
        existing_type=sa.String(length=40),
        type_=sa.String(length=50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "assets",
        "asset_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=40),
        existing_nullable=False,
    )

    op.drop_column("assets", "file_size_bytes")
    op.drop_column("assets", "mime_type")
    op.drop_column("assets", "source_format")
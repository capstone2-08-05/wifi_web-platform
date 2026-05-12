"""add patch_logs table

Revision ID: 20260511_0005
Revises: 20260510_0004
Create Date: 2026-05-11 09:00:00


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260511_0005"
down_revision: Union[str, Sequence[str], None] = "20260510_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patch_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scene_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("scene_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("patch_type", sa.String(length=20), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column(
            "target_id", postgresql.UUID(as_uuid=False), nullable=False
        ),
        sa.Column(
            "patch_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_patch_logs_version_target",
        "patch_logs",
        ["scene_version_id", "target_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_patch_logs_version_target", table_name="patch_logs")
    op.drop_table("patch_logs")

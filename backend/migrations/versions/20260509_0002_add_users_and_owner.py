"""add users table and owner_user_id/uploaded_by FKs

Revision ID: 20260509_0002
Revises: 20260330_0001
Create Date: 2026-05-09 14:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260509_0002"
down_revision: Union[str, Sequence[str], None] = "20260330_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email", "users", ["email"])

   
    op.add_column(
        "projects",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    )

   
    op.add_column(
        "projects",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=False), nullable=True),
    )

    op.execute(
        """
        DO $$
        DECLARE
            seed_user_id uuid;
            orphan_count int;
        BEGIN
            SELECT COUNT(*) INTO orphan_count FROM projects WHERE owner_user_id IS NULL;
            IF orphan_count > 0 THEN
                INSERT INTO users (email, password, name)
                VALUES ('system@local', 'NOT_USABLE', 'system')
                RETURNING id INTO seed_user_id;

                UPDATE projects SET owner_user_id = seed_user_id WHERE owner_user_id IS NULL;
            END IF;
        END $$;
        """
    )

    op.alter_column("projects", "owner_user_id", nullable=False)

    op.create_foreign_key(
        "fk_projects_owner_user_id",
        "projects",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_projects_owner_user_id", "projects", ["owner_user_id"])

    op.add_column(
        "assets",
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_assets_uploaded_by",
        "assets",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_assets_uploaded_by", "assets", ["uploaded_by"])


def downgrade() -> None:
    op.drop_index("idx_assets_uploaded_by", table_name="assets")
    op.drop_constraint("fk_assets_uploaded_by", "assets", type_="foreignkey")
    op.drop_column("assets", "uploaded_by")

    op.drop_index("idx_projects_owner_user_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_user_id", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_user_id")
    op.drop_column("projects", "status")

    
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
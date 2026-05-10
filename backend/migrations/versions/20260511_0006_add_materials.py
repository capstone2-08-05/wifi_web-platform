"""add materials + material_rf_profiles + seed default materials

Revision ID: 20260511_0006
Revises: 20260511_0005
Create Date: 2026-05-11 14:00:00


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260511_0006"
down_revision: Union[str, Sequence[str], None] = "20260511_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_MATERIALS = [
    # (code, name, category, profiles[(freq_ghz, perm, cond, loss_db, ref_thick, is_default)])
    (
        "concrete",
        "콘크리트",
        "structural",
        [
            (2.4, 4.5, 0.014, 12.3, 0.20, True),
            (5.0, 4.4, 0.030, 18.5, 0.20, False),
        ],
    ),
    (
        "drywall",
        "석고보드",
        "interior",
        [
            (2.4, 2.7, 0.005, 3.2, 0.013, True),
            (5.0, 2.6, 0.010, 4.5, 0.013, False),
        ],
    ),
    (
        "glass",
        "유리",
        "glass",
        [
            (2.4, 6.3, 0.000, 2.0, 0.006, True),
            (5.0, 6.2, 0.001, 3.0, 0.006, False),
        ],
    ),
    (
        "brick",
        "벽돌",
        "structural",
        [
            (2.4, 3.9, 0.020, 7.5, 0.10, True),
            (5.0, 3.8, 0.040, 11.0, 0.10, False),
        ],
    ),
    (
        "wood",
        "목재",
        "interior",
        [
            (2.4, 2.0, 0.001, 2.8, 0.04, True),
            (5.0, 1.9, 0.003, 4.0, 0.04, False),
        ],
    ),
]


def upgrade() -> None:
    materials = op.create_table(
        "materials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("material_code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("material_name", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    rf_profiles = op.create_table(
        "material_rf_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("freq_ghz", sa.Numeric(6, 3), nullable=False),
        sa.Column("permittivity", sa.Numeric(8, 4), nullable=False),
        sa.Column("conductivity", sa.Numeric(8, 6), nullable=False),
        sa.Column("penetration_loss_db", sa.Numeric(8, 3), nullable=False),
        sa.Column("reference_thickness_m", sa.Numeric(6, 4), nullable=False),
        sa.Column(
            "profile_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_material_rf_profiles_material_freq",
        "material_rf_profiles",
        ["material_id", "freq_ghz"],
    )

    bind = op.get_bind()
    for code, name, category, profiles in SEED_MATERIALS:
        material_id = bind.execute(
            sa.text(
                "INSERT INTO materials (material_code, material_name, category) "
                "VALUES (:code, :name, :cat) RETURNING id"
            ),
            {"code": code, "name": name, "cat": category},
        ).scalar_one()
        for freq, perm, cond, loss, thick, is_default in profiles:
            bind.execute(
                sa.text(
                    "INSERT INTO material_rf_profiles "
                    "(material_id, freq_ghz, permittivity, conductivity, "
                    "penetration_loss_db, reference_thickness_m, is_default) "
                    "VALUES (:mid, :freq, :perm, :cond, :loss, :thick, :is_default)"
                ),
                {
                    "mid": material_id,
                    "freq": freq,
                    "perm": perm,
                    "cond": cond,
                    "loss": loss,
                    "thick": thick,
                    "is_default": is_default,
                },
            )


def downgrade() -> None:
    op.drop_index(
        "idx_material_rf_profiles_material_freq",
        table_name="material_rf_profiles",
    )
    op.drop_table("material_rf_profiles")
    op.drop_table("materials")

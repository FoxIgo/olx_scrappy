"""components, component aliases and benchmark scores (ADR 0011)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _component_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["component_id"],
        ["components.id"],
        name=op.f(f"fk_{table}_component_id_components"),
        initially="DEFERRED",
        deferrable=True,
    )


def upgrade() -> None:
    op.create_table(
        "components",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=True),
        sa.Column("family", sa.String(length=64), nullable=True),
        sa.Column("generation", sa.String(length=16), nullable=True),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_components")),
        sa.UniqueConstraint("kind", "slug", name="uq_components_kind_slug"),
    )
    op.create_index("ix_components_kind", "components", ["kind"], unique=False)

    op.create_table(
        "component_aliases",
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("component_id", sa.String(length=160), nullable=False),
        _component_fk("component_aliases"),
        sa.PrimaryKeyConstraint("kind", "alias", name=op.f("pk_component_aliases")),
    )
    op.create_index(
        "ix_component_aliases_component_id", "component_aliases", ["component_id"], unique=False
    )

    op.create_table(
        "component_benchmarks",
        sa.Column("component_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        _component_fk("component_benchmarks"),
        sa.PrimaryKeyConstraint(
            "component_id", "source", "metric", name=op.f("pk_component_benchmarks")
        ),
    )


def downgrade() -> None:
    op.drop_table("component_benchmarks")
    op.drop_index("ix_component_aliases_component_id", table_name="component_aliases")
    op.drop_table("component_aliases")
    op.drop_index("ix_components_kind", table_name="components")
    op.drop_table("components")

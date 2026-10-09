"""offer -> component links (ADR 0011 section 3)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offer_components",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("component_id", sa.String(length=160), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("resolver_version", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source", "external_id"],
            ["offers.source", "offers.external_id"],
            name=op.f("fk_offer_components_source_offers"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            name=op.f("fk_offer_components_component_id_components"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("source", "external_id", "kind", name=op.f("pk_offer_components")),
    )
    op.create_index(
        "ix_offer_components_component_id", "offer_components", ["component_id"], unique=False
    )
    op.create_index("ix_offer_components_method", "offer_components", ["kind", "method"])


def downgrade() -> None:
    op.drop_index("ix_offer_components_method", table_name="offer_components")
    op.drop_index("ix_offer_components_component_id", table_name="offer_components")
    op.drop_table("offer_components")

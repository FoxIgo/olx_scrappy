"""offer seller activity (created_at, last_seen_at, is_online)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15 19:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offers", sa.Column("seller_created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "offers", sa.Column("seller_last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("offers", sa.Column("seller_is_online", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("offers", "seller_is_online")
    op.drop_column("offers", "seller_last_seen_at")
    op.drop_column("offers", "seller_created_at")

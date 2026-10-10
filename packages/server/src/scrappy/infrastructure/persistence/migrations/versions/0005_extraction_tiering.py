"""tiering: rule pass markers and LLM escalation on extraction_state (ADR 0012)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_state") as batch:
        batch.add_column(sa.Column("rules_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("rules_version", sa.String(length=96), nullable=True))
        batch.add_column(sa.Column("escalation", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("extraction_state") as batch:
        batch.drop_column("escalation")
        batch.drop_column("rules_version")
        batch.drop_column("rules_hash")

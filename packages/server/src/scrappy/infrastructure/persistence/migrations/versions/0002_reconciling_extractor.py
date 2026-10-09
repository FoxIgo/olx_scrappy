"""reconciling extractor (ADR 0010)

* extraction_state, extraction_batches (+ items), extraction_profile_status
* provenance columns on extractions (catalog fingerprint, profile, provider, batch id,
  cost_estimated)
* unfinished / failed ``extract_offer`` jobs become ``obsolete``: extraction is no longer a
  job. Runs left RUNNING only because of them are closed by the scraper loop at start
  (``FinalizeIdleRuns``), which needs application logic a migration must not contain.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBSOLETE_NOTE = "superseded by the extraction reconciler (ADR 0010)"


def _offer_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["source", "external_id"],
        ["offers.source", "offers.external_id"],
        name=op.f(f"fk_{table}_source_offers"),
        initially="DEFERRED",
        deferrable=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("extractions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("catalog_fingerprint", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("profile", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("provider", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("batch_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("cost_estimated", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "extraction_state",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("lease_owner", sa.String(length=80), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("parked", sa.Boolean(), nullable=False),
        sa.Column("target_content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_catalog_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("target_prompt_version", sa.String(length=64), nullable=True),
        sa.Column("forced", sa.Boolean(), nullable=False),
        sa.Column("requested_profile", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _offer_fk("extraction_state"),
        sa.PrimaryKeyConstraint("source", "external_id", name=op.f("pk_extraction_state")),
    )
    with op.batch_alter_table("extraction_state", schema=None) as batch_op:
        batch_op.create_index("ix_extraction_state_lease_owner", ["lease_owner"], unique=False)
        batch_op.create_index("ix_extraction_state_parked", ["parked"], unique=False)

    op.create_table(
        "extraction_batches",
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("catalog_fingerprint", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("provider_batch_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("submitting_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.String(length=64), nullable=True),
        sa.Column("succeeded", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("stale", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_extraction_batches")),
        sa.UniqueConstraint("id", name=op.f("uq_extraction_batches_id")),
    )
    with op.batch_alter_table("extraction_batches", schema=None) as batch_op:
        batch_op.create_index("ix_extraction_batches_status", ["status", "profile"], unique=False)

    op.create_table(
        "extraction_batch_items",
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["extraction_batches.id"],
            name=op.f("fk_extraction_batch_items_batch_id_extraction_batches"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("batch_id", "position", name=op.f("pk_extraction_batch_items")),
    )
    with op.batch_alter_table("extraction_batch_items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_extraction_batch_items_offer", ["source", "external_id"], unique=False
        )

    op.create_table(
        "extraction_profile_status",
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("blocked_until", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("usage_day", sa.String(length=10), nullable=True),
        sa.Column("requests_today", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("profile", name=op.f("pk_extraction_profile_status")),
    )

    # Extraction is no longer a job: unfinished and failed extract_offer jobs never run.
    jobs = sa.table(
        "jobs",
        sa.column("type", sa.String),
        sa.column("status", sa.String),
        sa.column("last_error", sa.Text),
        sa.column("finished_at", sa.DateTime),
    )
    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, like UtcDateTime
    op.execute(
        jobs.update()
        .where(
            jobs.c.type == "extract_offer",
            jobs.c.status.in_(["pending", "running", "failed"]),
        )
        .values(
            status="obsolete",
            last_error=sa.func.coalesce(jobs.c.last_error + "; ", "") + OBSOLETE_NOTE,
            finished_at=sa.func.coalesce(jobs.c.finished_at, now),
        )
    )


def downgrade() -> None:
    op.execute(
        "UPDATE jobs SET status = 'failed' WHERE type = 'extract_offer' AND status = 'obsolete'"
    )
    op.drop_table("extraction_profile_status")
    with op.batch_alter_table("extraction_batch_items", schema=None) as batch_op:
        batch_op.drop_index("ix_extraction_batch_items_offer")
    op.drop_table("extraction_batch_items")
    with op.batch_alter_table("extraction_batches", schema=None) as batch_op:
        batch_op.drop_index("ix_extraction_batches_status")
    op.drop_table("extraction_batches")
    with op.batch_alter_table("extraction_state", schema=None) as batch_op:
        batch_op.drop_index("ix_extraction_state_parked")
        batch_op.drop_index("ix_extraction_state_lease_owner")
    op.drop_table("extraction_state")
    with op.batch_alter_table("extractions", schema=None) as batch_op:
        batch_op.drop_column("cost_estimated")
        batch_op.drop_column("batch_id")
        batch_op.drop_column("provider")
        batch_op.drop_column("profile")
        batch_op.drop_column("catalog_fingerprint")

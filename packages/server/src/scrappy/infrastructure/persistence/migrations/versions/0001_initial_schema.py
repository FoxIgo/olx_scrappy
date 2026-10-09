"""initial schema

Timestamps are naive UTC (see tables.UtcDateTime).

Revision ID: 0001
Revises:
Create Date: 2026-10-09 17:47:04.522675
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "jobs",
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_jobs")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_jobs_dedup_key")),
        sa.UniqueConstraint("id", name=op.f("uq_jobs_id")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index("ix_jobs_claim", ["status", "available_at", "seq"], unique=False)
        batch_op.create_index("ix_jobs_run", ["run_id", "status"], unique=False)

    op.create_table(
        "offers",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("price_kind", sa.String(length=16), nullable=True),
        sa.Column("price_amount", sa.String(length=64), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=True),
        sa.Column("price_negotiable", sa.Boolean(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("seller_external_id", sa.Text(), nullable=True),
        sa.Column("seller_name", sa.Text(), nullable=True),
        sa.Column("seller_is_business", sa.Boolean(), nullable=True),
        sa.Column("image_urls", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("details_fetched_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("source", "external_id", name=op.f("pk_offers")),
    )
    with op.batch_alter_table("offers", schema=None) as batch_op:
        batch_op.create_index("ix_offers_last_seen_at", ["last_seen_at"], unique=False)

    op.create_table(
        "saved_searches",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_saved_searches")),
    )
    op.create_table(
        "extractions",
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("attributes", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source", "external_id"],
            ["offers.source", "offers.external_id"],
            name=op.f("fk_extractions_source_offers"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_extractions")),
    )
    with op.batch_alter_table("extractions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_extractions_latest", ["source", "external_id", "extracted_at", "seq"], unique=False
        )

    op.create_table(
        "offer_snapshots",
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("changes", sa.JSON(none_as_null=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source", "external_id"],
            ["offers.source", "offers.external_id"],
            name=op.f("fk_offer_snapshots_source_offers"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_offer_snapshots")),
    )
    with op.batch_alter_table("offer_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "ix_offer_snapshots_offer", ["source", "external_id", "seq"], unique=False
        )

    op.create_table(
        "scrape_runs",
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("search", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("metrics", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("reasons", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("errors", sa.JSON(none_as_null=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search"],
            ["saved_searches.name"],
            name=op.f("fk_scrape_runs_search_saved_searches"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_scrape_runs")),
        sa.UniqueConstraint("id", name=op.f("uq_scrape_runs_id")),
    )
    with op.batch_alter_table("scrape_runs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_scrape_runs_search", ["search", "status", "started_at"], unique=False
        )

    op.create_table(
        "search_offers",
        sa.Column("search", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("derived_relevance", sa.Boolean(), nullable=True),
        sa.Column("relevance_override", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["search"],
            ["saved_searches.name"],
            name=op.f("fk_search_offers_search_saved_searches"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["source", "external_id"],
            ["offers.source", "offers.external_id"],
            name=op.f("fk_search_offers_source_offers"),
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("search", "source", "external_id", name=op.f("pk_search_offers")),
    )
    with op.batch_alter_table("search_offers", schema=None) as batch_op:
        batch_op.create_index("ix_search_offers_listing", ["search", "last_seen_at"], unique=False)
        batch_op.create_index("ix_search_offers_offer", ["source", "external_id"], unique=False)


def downgrade() -> None:

    with op.batch_alter_table("search_offers", schema=None) as batch_op:
        batch_op.drop_index("ix_search_offers_offer")
        batch_op.drop_index("ix_search_offers_listing")

    op.drop_table("search_offers")
    with op.batch_alter_table("scrape_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_scrape_runs_search")

    op.drop_table("scrape_runs")
    with op.batch_alter_table("offer_snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_offer_snapshots_offer")

    op.drop_table("offer_snapshots")
    with op.batch_alter_table("extractions", schema=None) as batch_op:
        batch_op.drop_index("ix_extractions_latest")

    op.drop_table("extractions")
    op.drop_table("saved_searches")
    with op.batch_alter_table("offers", schema=None) as batch_op:
        batch_op.drop_index("ix_offers_last_seen_at")

    op.drop_table("offers")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_run")
        batch_op.drop_index("ix_jobs_claim")

    op.drop_table("jobs")

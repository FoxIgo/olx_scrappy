"""SQLAlchemy Core table definitions (the schema of record; Alembic migrates to it).

Portable on purpose: only types and constructs that SQLite and PostgreSQL share.

Storage conventions
-------------------
* **Datetimes** are stored as naive UTC (:class:`UtcDateTime`) and come back timezone-aware
  (UTC). SQLite has no timezone type and silently drops tzinfo, so the conversion is
  explicit. Naive values are rejected on the way in.
* **Money** is text holding ``str(Decimal)`` (exact, keeps the exponent such as ``10.50``).
  ``Numeric`` would round-trip through float on SQLite. Amounts are never compared in SQL.
* **JSON** columns (params, image urls, attributes, change lists, metrics, job payloads)
  use SQLAlchemy's portable ``JSON`` (TEXT on SQLite, JSON on PostgreSQL); a Python ``None``
  is stored as SQL ``NULL``, not as the JSON ``null``.
* **Booleans** use ``Boolean``; tri-state values (relevance) are nullable.
* Foreign keys are ``DEFERRABLE INITIALLY DEFERRED`` so a unit of work may write rows in any
  order; they are checked at commit.
* Offer identity is two columns, ``(source, external_id)``, matching ``OfferId``; the
  composite primary key is also the lookup index.
* Tables with an insertion-ordered history (snapshots, extractions, runs, jobs) have an
  autoincrement ``seq`` primary key; ties on timestamps are broken by it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes stored as naive UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime cannot be stored; use timezone-aware values")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def _json() -> JSON:
    return JSON(none_as_null=True)


def _seq() -> Column[Any]:
    """Autoincrement surrogate key; also the insertion order (FIFO ties, history)."""
    return Column(
        "seq", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )


def _fk(columns: list[str], target: str, refcolumns: list[str]) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        columns, [f"{target}.{c}" for c in refcolumns], deferrable=True, initially="DEFERRED"
    )


saved_searches = Table(
    "saved_searches",
    metadata,
    Column("name", String(64), primary_key=True),
    Column("source", String(64), nullable=False),
    Column("url", Text, nullable=False),
    Column("category", String(64), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("last_run_at", UtcDateTime),
)

offers = Table(
    "offers",
    metadata,
    Column("source", String(64), primary_key=True),
    Column("external_id", String(255), primary_key=True),
    Column("url", Text, nullable=False),
    Column("first_seen_at", UtcDateTime, nullable=False),
    Column("last_seen_at", UtcDateTime, nullable=False),
    Column("title", Text),
    Column("price_kind", String(16)),
    Column("price_amount", String(64)),
    Column("price_currency", String(3)),
    Column("price_negotiable", Boolean),
    Column("location", Text),
    Column("thumbnail_url", Text),
    Column("posted_at", UtcDateTime),
    Column("refreshed_at", UtcDateTime),
    Column("description", Text),
    Column("params", _json()),
    Column("status", String(16), nullable=False),
    Column("seller_external_id", Text),
    Column("seller_name", Text),
    Column("seller_is_business", Boolean),
    Column("image_urls", _json(), nullable=False),
    Column("content_hash", String(64)),
    Column("details_fetched_at", UtcDateTime),
    Index("ix_offers_last_seen_at", "last_seen_at"),
)

offer_snapshots = Table(
    "offer_snapshots",
    metadata,
    _seq(),
    Column("source", String(64), nullable=False),
    Column("external_id", String(255), nullable=False),
    Column("observed_at", UtcDateTime, nullable=False),
    Column("run_id", String(64)),
    Column("changes", _json(), nullable=False),
    _fk(["source", "external_id"], "offers", ["source", "external_id"]),
    Index("ix_offer_snapshots_offer", "source", "external_id", "seq"),
)

search_offers = Table(
    "search_offers",
    metadata,
    Column("search", String(64), primary_key=True),
    Column("source", String(64), primary_key=True),
    Column("external_id", String(255), primary_key=True),
    Column("first_seen_at", UtcDateTime, nullable=False),
    Column("last_seen_at", UtcDateTime, nullable=False),
    Column("derived_relevance", Boolean),
    Column("relevance_override", Boolean),
    _fk(["search"], "saved_searches", ["name"]),
    _fk(["source", "external_id"], "offers", ["source", "external_id"]),
    Index("ix_search_offers_offer", "source", "external_id"),
    Index("ix_search_offers_listing", "search", "last_seen_at"),
)

extractions = Table(
    "extractions",
    metadata,
    _seq(),
    Column("source", String(64), nullable=False),
    Column("external_id", String(255), nullable=False),
    Column("category", String(64), nullable=False),
    Column("attributes", _json(), nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("schema_version", Integer),
    Column("content_hash", String(64), nullable=False),
    Column("extracted_at", UtcDateTime, nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("cost_usd", String(64)),
    Column("notes", Text),
    # provenance added by ADR 0010 (NULL for older rows)
    Column("catalog_fingerprint", String(32)),
    Column("profile", String(64)),
    Column("provider", String(64)),
    Column("batch_id", String(64)),
    Column("cost_estimated", Boolean, nullable=False, server_default=false()),
    _fk(["source", "external_id"], "offers", ["source", "external_id"]),
    # "latest extraction of an offer": order by extracted_at, then insertion
    Index("ix_extractions_latest", "source", "external_id", "extracted_at", "seq"),
)

scrape_runs = Table(
    "scrape_runs",
    metadata,
    _seq(),
    Column("id", String(64), nullable=False, unique=True),
    Column("search", String(64), nullable=False),
    Column("source", String(64), nullable=False),
    Column("started_at", UtcDateTime, nullable=False),
    Column("status", String(16), nullable=False),
    Column("finished_at", UtcDateTime),
    Column("metrics", _json(), nullable=False),
    Column("reasons", _json(), nullable=False),
    Column("warnings", _json(), nullable=False),
    Column("errors", _json(), nullable=False),
    _fk(["search"], "saved_searches", ["name"]),
    Index("ix_scrape_runs_search", "search", "status", "started_at"),
)

jobs = Table(
    "jobs",
    metadata,
    _seq(),
    Column("id", String(64), nullable=False, unique=True),
    Column("type", String(32), nullable=False),
    Column("payload", _json(), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("dedup_key", Text, nullable=False, unique=True),
    Column("run_id", String(64)),
    Column("created_at", UtcDateTime, nullable=False),
    Column("available_at", UtcDateTime, nullable=False),
    Column("finished_at", UtcDateTime),
    Column("result", _json()),
    Column("last_error", Text),
    # claim: PENDING + due + FIFO (available_at, then insertion order)
    Index("ix_jobs_claim", "status", "available_at", "seq"),
    Index("ix_jobs_run", "run_id", "status"),
)

# ---------------------------------------------------------------- extraction (ADR 0010)

extraction_state = Table(
    "extraction_state",
    metadata,
    Column("source", String(64), primary_key=True),
    Column("external_id", String(255), primary_key=True),
    Column("lease_owner", String(80)),
    Column("lease_until", UtcDateTime),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
    Column("next_attempt_at", UtcDateTime),
    Column("parked", Boolean, nullable=False),
    # the target the failure counters refer to
    Column("target_content_hash", String(64)),
    Column("target_catalog_fingerprint", String(32)),
    Column("target_prompt_version", String(64)),
    Column("forced", Boolean, nullable=False),
    Column("requested_profile", String(64)),
    Column("updated_at", UtcDateTime, nullable=False),
    _fk(["source", "external_id"], "offers", ["source", "external_id"]),
    Index("ix_extraction_state_lease_owner", "lease_owner"),
    Index("ix_extraction_state_parked", "parked"),
)

extraction_batches = Table(
    "extraction_batches",
    metadata,
    _seq(),
    Column("id", String(64), nullable=False, unique=True),
    Column("profile", String(64), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", String(64), nullable=False),
    Column("catalog_fingerprint", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("parent_id", String(64)),
    Column("provider_batch_id", Text),
    Column("created_at", UtcDateTime, nullable=False),
    Column("submitting_at", UtcDateTime),
    Column("submitted_at", UtcDateTime),
    Column("finished_at", UtcDateTime),
    Column("item_count", Integer, nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("cost_usd", String(64)),
    Column("succeeded", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("stale", Integer, nullable=False),
    Column("error", Text),
    Index("ix_extraction_batches_status", "status", "profile"),
)

extraction_batch_items = Table(
    "extraction_batch_items",
    metadata,
    Column("batch_id", String(64), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("source", String(64), nullable=False),
    Column("external_id", String(255), nullable=False),
    Column("content_hash", String(64), nullable=False),
    _fk(["batch_id"], "extraction_batches", ["id"]),
    Index("ix_extraction_batch_items_offer", "source", "external_id"),
)

extraction_profile_status = Table(
    "extraction_profile_status",
    metadata,
    Column("profile", String(64), primary_key=True),
    Column("blocked_until", UtcDateTime),
    Column("reason", Text),
    Column("usage_day", String(10)),
    Column("requests_today", Integer, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
)

components = Table(
    "components",
    metadata,
    Column("id", String(160), primary_key=True),
    Column("kind", String(8), nullable=False),
    Column("slug", String(150), nullable=False),
    Column("name", Text, nullable=False),
    Column("vendor", String(32)),
    Column("family", String(64)),
    Column("generation", String(16)),
    Column("segment", String(16), nullable=False),
    UniqueConstraint("kind", "slug", name="uq_components_kind_slug"),
    Index("ix_components_kind", "kind"),
)

component_aliases = Table(
    "component_aliases",
    metadata,
    Column("kind", String(8), primary_key=True),
    Column("alias", String(200), primary_key=True),
    Column("component_id", String(160), nullable=False),
    _fk(["component_id"], "components", ["id"]),
    Index("ix_component_aliases_component_id", "component_id"),
)

component_benchmarks = Table(
    "component_benchmarks",
    metadata,
    Column("component_id", String(160), primary_key=True),
    Column("source", String(64), primary_key=True),
    Column("metric", String(64), primary_key=True),
    Column("score", Float, nullable=False),
    Column("samples", Integer, nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    _fk(["component_id"], "components", ["id"]),
)

offer_components = Table(
    "offer_components",
    metadata,
    Column("source", String(64), primary_key=True),
    Column("external_id", String(255), primary_key=True),
    Column("kind", String(8), primary_key=True),
    Column("component_id", String(160)),
    Column("raw_text", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("method", String(16), nullable=False),
    Column("resolver_version", Integer, nullable=False),
    Column("resolved_at", UtcDateTime, nullable=False),
    _fk(["source", "external_id"], "offers", ["source", "external_id"]),
    _fk(["component_id"], "components", ["id"]),
    Index("ix_offer_components_component_id", "component_id"),
    Index("ix_offer_components_method", "kind", "method"),
)

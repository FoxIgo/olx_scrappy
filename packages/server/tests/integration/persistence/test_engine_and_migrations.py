"""Engine pragmas, Alembic migrations and schema/metadata agreement."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import inspect, text

from scrappy.infrastructure.persistence import (
    create_engine,
    sqlite_url,
    upgrade_to_head,
    upgrade_to_head_async,
)
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence.migrate import alembic_config, sync_url
from scrappy.infrastructure.persistence.tables import metadata
from tests.integration.persistence.sqlstore import SqlStore

TABLES = {
    "saved_searches",
    "offers",
    "offer_snapshots",
    "search_offers",
    "extractions",
    "scrape_runs",
    "jobs",
    "extraction_state",
    "extraction_batches",
    "extraction_batch_items",
    "extraction_profile_status",
}


async def test_pragmas_are_applied_to_every_connection(store: SqlStore) -> None:
    for _ in range(2):  # pooled and fresh connections alike
        async with store.engine.connect() as conn:
            assert (await conn.execute(text("pragma journal_mode"))).scalar_one() == "wal"
            assert (await conn.execute(text("pragma foreign_keys"))).scalar_one() == 1
            assert (await conn.execute(text("pragma busy_timeout"))).scalar_one() == 30_000


def test_upgrade_to_head_creates_the_schema_and_is_repeatable(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "m.db")
    upgrade_to_head(url)
    upgrade_to_head(url)  # already at head: no-op
    engine = create_sync_engine(sync_url(url))
    try:
        names = set(inspect(engine).get_table_names())
        assert names >= TABLES and "alembic_version" in names
        with engine.connect() as conn:
            assert conn.execute(text("select version_num from alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_migrations_produce_exactly_the_declared_schema(tmp_path: Path) -> None:
    """Fails when tables.py changes without a new migration (schema drift)."""
    url = sqlite_url(tmp_path / "drift.db")
    upgrade_to_head(url)
    engine = create_sync_engine(sync_url(url))
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), metadata)
        assert diff == []
    finally:
        engine.dispose()


def test_schema_has_the_hot_path_indexes(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "ix.db")
    upgrade_to_head(url)
    engine = create_sync_engine(sync_url(url))
    try:
        inspector = inspect(engine)

        def indexed(table: str) -> set[tuple[str, ...]]:
            columns = {tuple(i["column_names"]) for i in inspector.get_indexes(table)}
            columns |= {tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)}
            return {tuple(str(c) for c in cols) for cols in columns}

        assert ("dedup_key",) in indexed("jobs")
        assert ("status", "available_at", "seq") in indexed("jobs")
        assert ("run_id", "status") in indexed("jobs")
        assert ("search", "last_seen_at") in indexed("search_offers")
        assert inspector.get_pk_constraint("offers")["constrained_columns"] == [
            "source",
            "external_id",
        ]
    finally:
        engine.dispose()


async def test_upgrade_through_an_existing_async_engine(tmp_path: Path) -> None:
    engine = create_engine(sqlite_url(tmp_path / "async.db"))
    try:
        await upgrade_to_head_async(engine)
        await upgrade_to_head_async(engine)
        async with engine.connect() as conn:
            tables = (
                await conn.execute(text("select name from sqlite_master where type = 'table'"))
            ).scalars()
            assert set(tables) >= TABLES
    finally:
        await engine.dispose()


def test_sync_url_maps_async_drivers() -> None:
    assert sync_url("sqlite+aiosqlite:///x.db") == "sqlite:///x.db"
    assert sync_url("postgresql+asyncpg://u:p%40@h/db") == "postgresql+psycopg://u:p%40@h/db"


def test_upgrade_from_0001_marks_old_extract_offer_jobs_obsolete(tmp_path: Path) -> None:
    """An existing database (jobs from the pre-ADR-0010 pipeline) upgrades cleanly."""
    url = sqlite_url(tmp_path / "old.db")
    command.upgrade(alembic_config(url), "0001")
    engine = create_sync_engine(sync_url(url))
    jobs = [
        ("j1", "extract_offer", "done", None),
        ("j2", "extract_offer", "pending", None),
        ("j3", "extract_offer", "running", None),
        ("j4", "extract_offer", "failed", "OPENROUTER_API_KEY is not set"),
        ("j5", "discover_page", "pending", None),
    ]
    try:
        with engine.begin() as conn:
            for job_id, job_type, status, error in jobs:
                conn.execute(
                    text(
                        "INSERT INTO jobs (id, type, payload, status, attempts, dedup_key, "
                        "created_at, available_at, last_error) VALUES (:id, :type, '{}', "
                        ":status, 1, :id, '2026-10-01 12:00:00', '2026-10-01 12:00:00', :error)"
                    ),
                    {"id": job_id, "type": job_type, "status": status, "error": error},
                )
            conn.execute(
                text(
                    "INSERT INTO offers (source, external_id, url, first_seen_at, last_seen_at, "
                    "status, image_urls, content_hash) VALUES ('olx_pl', '1', 'u', "
                    "'2026-10-01 12:00:00', '2026-10-01 12:00:00', 'active', '[]', :hash)"
                ),
                {"hash": "a" * 64},
            )
            conn.execute(
                text(
                    "INSERT INTO extractions (source, external_id, category, attributes, model, "
                    "prompt_version, schema_version, content_hash, extracted_at, prompt_tokens, "
                    "completion_tokens) VALUES ('olx_pl', '1', 'other', '{}', 'm', "
                    "'extract-v1', NULL, :hash, '2026-10-01 12:00:00', 1, 2)"
                ),
                {"hash": "a" * 64},
            )

        upgrade_to_head(url)

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, status, last_error, finished_at FROM jobs ORDER BY id")
            ).all()
            statuses = {row[0]: row[1] for row in rows}
            assert statuses == {
                "j1": "done",
                "j2": "obsolete",
                "j3": "obsolete",
                "j4": "obsolete",
                "j5": "pending",
            }
            errors = {row[0]: row[2] for row in rows}
            assert "ADR 0010" in errors["j2"]
            assert errors["j4"].startswith("OPENROUTER_API_KEY is not set; ")
            assert all(row[3] is not None for row in rows if row[1] == "obsolete")
            from scrappy.infrastructure.persistence.tables import extractions

            row = conn.execute(extractions.select()).mappings().one()
            legacy = m.extraction_from(row, extractions.c)
            assert legacy.provenance.catalog_fingerprint is None
            assert legacy.provenance.profile is None
            assert legacy.provenance.cost_estimated is False
    finally:
        engine.dispose()

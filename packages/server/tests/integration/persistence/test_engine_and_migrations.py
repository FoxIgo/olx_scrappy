"""Engine pragmas, Alembic migrations and schema/metadata agreement."""

from __future__ import annotations

from pathlib import Path

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
from scrappy.infrastructure.persistence.migrate import sync_url
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

"""Programmatic Alembic: migrate a database to the latest schema on application start.

``upgrade_to_head(url)`` is synchronous (call it before the event loop starts, or via
``asyncio.to_thread``) and accepts the *async* application URL: it is mapped to the matching
sync driver (``sqlite+aiosqlite`` -> ``sqlite``, ``postgresql+asyncpg`` ->
``postgresql+psycopg``; a psycopg install is then needed for PostgreSQL).
``upgrade_to_head_async(engine)`` migrates through an existing async engine instead and is
safe inside a running event loop.

The scripts live in the ``migrations`` directory next to this module (shipped with the
package); there is no ``alembic.ini``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine

SCRIPT_LOCATION = Path(__file__).parent / "migrations"

_SYNC_DRIVERS = {
    "sqlite+aiosqlite": "sqlite",
    "postgresql+asyncpg": "postgresql+psycopg",
}


def sync_url(url: str) -> str:
    """The sync-driver equivalent of an async application URL."""
    parsed = make_url(url)
    driver = _SYNC_DRIVERS.get(parsed.drivername, parsed.drivername)
    return parsed.set(drivername=driver).render_as_string(hide_password=False)


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    if url is not None:
        config.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    return config


def upgrade_to_head(engine_url: str) -> None:
    """Create or upgrade the database at ``engine_url`` to the latest revision."""
    command.upgrade(alembic_config(engine_url), "head")


async def upgrade_to_head_async(engine: AsyncEngine) -> None:
    """Same, through an existing async engine (usable inside a running event loop)."""

    def _upgrade(connection: Connection) -> None:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)

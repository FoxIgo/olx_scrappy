"""Async engine setup.

Driver choice: the application ports are ``async``, so persistence uses SQLAlchemy's asyncio
extension. SQLite goes through ``aiosqlite`` (``sqlite+aiosqlite:///path``). Switching to
PostgreSQL later is a URL change to ``postgresql+asyncpg://...``: all SQL here is Core and
portable; dialect-specific spots are isolated (``_sql.py``: upsert / insert-ignore).

SQLite specifics (installed on every new connection):

* ``journal_mode=WAL``: readers (queries, CLI) do not block the single writer.
* ``foreign_keys=ON``: SQLite ignores foreign keys unless asked, per connection.
* ``busy_timeout``: a second writer waits for the lock instead of failing at once.
* ``synchronous=NORMAL``: safe with WAL, much faster commits.
* Transactions start with ``BEGIN IMMEDIATE`` (the pysqlite driver would otherwise delay
  ``BEGIN`` until the first write and fail with "database is locked" on lock upgrade). A
  connection marked read-only (``execution_options(scrappy_read_only=True)``) uses a plain
  deferred ``BEGIN``, which under WAL reads a consistent snapshot without blocking writers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

READ_ONLY_OPTION = "scrappy_read_only"
DEFAULT_BUSY_TIMEOUT_MS = 30_000


def sqlite_url(path: str | Path) -> str:
    """``sqlite+aiosqlite`` URL for a database file."""
    return f"sqlite+aiosqlite:///{Path(path).as_posix()}"


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def create_engine(url: str, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> AsyncEngine:
    """Create the async engine for ``url`` (``sqlite+aiosqlite`` or, later, ``asyncpg``)."""
    engine = create_async_engine(url, json_serializer=_dumps)
    if make_url(url).get_backend_name() == "sqlite":
        configure_sqlite(engine.sync_engine, busy_timeout_ms=busy_timeout_ms)
    return engine


def configure_sqlite(engine: Any, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
    """Install the connection pragmas and ``BEGIN IMMEDIATE`` on a (sync) engine."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:  # pyright: ignore[reportUnusedFunction]
        dbapi_connection.isolation_level = None  # we emit BEGIN ourselves (see _on_begin)
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Connection) -> None:  # pyright: ignore[reportUnusedFunction]
        if connection.get_execution_options().get(READ_ONLY_OPTION):
            connection.exec_driver_sql("BEGIN")
        else:
            connection.exec_driver_sql("BEGIN IMMEDIATE")

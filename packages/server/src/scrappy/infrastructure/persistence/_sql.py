"""The few dialect-specific statements (SQLite and PostgreSQL share this syntax)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection

CHUNK = 400
"""Max key tuples per ``IN`` (SQLite's variable limit is 999 on old builds, 32766 on new)."""


def _insert(conn: AsyncConnection, table: Table) -> Any:
    name = conn.dialect.name
    if name == "sqlite":
        return sqlite_insert(table)
    if name == "postgresql":
        return pg_insert(table)
    raise NotImplementedError(f"unsupported database dialect {name!r}")


async def upsert(
    conn: AsyncConnection, table: Table, values: Mapping[str, Any], keys: Sequence[str]
) -> None:
    """INSERT ... ON CONFLICT (keys) DO UPDATE SET <all other columns>."""
    stmt = _insert(conn, table).values(dict(values))
    updates = {k: stmt.excluded[k] for k in values if k not in keys}
    if updates:
        stmt = stmt.on_conflict_do_update(index_elements=list(keys), set_=updates)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(keys))
    await conn.execute(stmt)


async def insert_ignore(
    conn: AsyncConnection, table: Table, values: Mapping[str, Any], keys: Sequence[str]
) -> bool:
    """INSERT ... ON CONFLICT (keys) DO NOTHING; True when a row was inserted."""
    stmt = (
        _insert(conn, table).values(dict(values)).on_conflict_do_nothing(index_elements=list(keys))
    )
    result = cast("CursorResult[Any]", await conn.execute(stmt))
    return result.rowcount > 0


def chunks[T](items: Sequence[T], size: int = CHUNK) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]

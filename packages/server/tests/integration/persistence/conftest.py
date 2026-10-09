from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from scrappy.infrastructure.persistence.queries import SqlOfferQueries
from scrappy.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from tests.integration.persistence.sqlstore import SqlStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqlStore]:
    """A migrated, empty SQLite database in a temp dir."""
    sql_store = SqlStore(tmp_path)
    yield sql_store
    await sql_store.close()


@pytest.fixture
def uow(store: SqlStore) -> Callable[[], SqlUnitOfWork]:
    return store.uow


@pytest.fixture
def queries(store: SqlStore) -> SqlOfferQueries:
    return SqlOfferQueries(store.engine)

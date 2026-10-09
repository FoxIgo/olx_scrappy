"""``SqlUnitOfWork``: one connection and one transaction per unit of work."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from scrappy.infrastructure.persistence.extraction_repositories import (
    SqlExtractionBatchRepository,
    SqlExtractionStateRepository,
    SqlProfileStatusRepository,
)
from scrappy.infrastructure.persistence.job_queue import SqlJobQueue
from scrappy.infrastructure.persistence.repositories import (
    SqlExtractionRepository,
    SqlOfferRepository,
    SqlSavedSearchRepository,
    SqlScrapeRunRepository,
    SqlSearchOfferRepository,
)


class SqlUnitOfWork:
    """Implements the ``UnitOfWork`` port over a pooled connection.

    ``__aenter__`` checks out a connection; its transaction begins with the first statement
    (``BEGIN IMMEDIATE`` on SQLite, see :mod:`.engine`). ``commit`` commits, ``rollback``
    discards; leaving the block without a commit rolls back. After ``commit`` or
    ``rollback`` the unit of work may be used again (a new transaction starts), exactly like
    the in-memory reference. The connection is released on exit.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._conn: AsyncConnection | None = None
        self._entered = False
        self._committed = False

    def _connection(self) -> AsyncConnection:
        if self._conn is None:
            raise RuntimeError("use the unit of work inside 'async with'")
        return self._conn

    @property
    def offers(self) -> SqlOfferRepository:
        return SqlOfferRepository(self._connection())

    @property
    def searches(self) -> SqlSavedSearchRepository:
        return SqlSavedSearchRepository(self._connection())

    @property
    def search_offers(self) -> SqlSearchOfferRepository:
        return SqlSearchOfferRepository(self._connection())

    @property
    def extractions(self) -> SqlExtractionRepository:
        return SqlExtractionRepository(self._connection())

    @property
    def runs(self) -> SqlScrapeRunRepository:
        return SqlScrapeRunRepository(self._connection())

    @property
    def jobs(self) -> SqlJobQueue:
        return SqlJobQueue(self._connection())

    @property
    def extraction_states(self) -> SqlExtractionStateRepository:
        return SqlExtractionStateRepository(self._connection())

    @property
    def extraction_batches(self) -> SqlExtractionBatchRepository:
        return SqlExtractionBatchRepository(self._connection())

    @property
    def profile_status(self) -> SqlProfileStatusRepository:
        return SqlProfileStatusRepository(self._connection())

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError("a unit of work is single-use")
        self._entered = True
        self._conn = await self._engine.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            if not self._committed or exc_type is not None:
                await conn.rollback()
        finally:
            self._conn = None
            await conn.close()

    async def commit(self) -> None:
        await self._connection().commit()
        self._committed = True

    async def rollback(self) -> None:
        await self._connection().rollback()
        self._committed = False


def sql_unit_of_work_factory(engine: AsyncEngine) -> Callable[[], SqlUnitOfWork]:
    """Use as the ``UnitOfWorkFactory``: ``uow=sql_unit_of_work_factory(engine)``."""

    def factory() -> SqlUnitOfWork:
        return SqlUnitOfWork(engine)

    return factory

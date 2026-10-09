"""``UnitOfWork``: the transaction boundary of the application.

Usage (always the same shape)::

    async with uow_factory() as uow:
        offer = await uow.offers.get(offer_id)
        ...
        await uow.jobs.enqueue(job)
        await uow.commit()

Contract for adapter authors
----------------------------
* ``__aenter__`` begins a transaction (SQLite: ``BEGIN IMMEDIATE`` on one connection;
  Postgres: a connection from the pool). All repositories and ``jobs`` share it.
* ``commit`` makes every write visible atomically. Leaving the block without ``commit``,
  or with an exception, rolls back. A unit of work is used for one transaction only.
* Use cases never do network I/O (site fetches, LLM calls) inside a unit of work; they
  read, release, call out, then open a new one to write. So transactions stay short and
  a single SQLite writer is enough (R12, R13).
* Concurrency between units of work: serialisable is assumed (true for SQLite's single
  writer). A Postgres adapter should use ``SERIALIZABLE`` or row locks on the job queue.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from scrappy.application.ports.job_queue import JobQueue
from scrappy.application.ports.repositories import (
    ExtractionBatchRepository,
    ExtractionRepository,
    ExtractionStateRepository,
    OfferRepository,
    ProfileStatusRepository,
    SavedSearchRepository,
    ScrapeRunRepository,
    SearchOfferRepository,
)


class UnitOfWork(Protocol):
    @property
    def offers(self) -> OfferRepository: ...
    @property
    def searches(self) -> SavedSearchRepository: ...
    @property
    def search_offers(self) -> SearchOfferRepository: ...
    @property
    def extractions(self) -> ExtractionRepository: ...
    @property
    def runs(self) -> ScrapeRunRepository: ...
    @property
    def jobs(self) -> JobQueue: ...
    @property
    def extraction_states(self) -> ExtractionStateRepository: ...
    @property
    def extraction_batches(self) -> ExtractionBatchRepository: ...
    @property
    def profile_status(self) -> ProfileStatusRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless ``commit`` was called."""
        ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


type UnitOfWorkFactory = Callable[[], UnitOfWork]
"""Creates a fresh unit of work per transaction (wired in ``main.py``)."""

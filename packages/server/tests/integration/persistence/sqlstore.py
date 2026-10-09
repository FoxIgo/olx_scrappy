"""A SQLite-backed stand-in for ``tests.unit.fakes.InMemoryStore``.

``SqlStore`` offers the same surface the application tests use (``uow()`` and a ``state``
snapshot of the committed data), so the existing in-memory scenario tests can run unchanged
against the real SQL adapters (see ``test_unit_suite_on_sql.py``).

``state`` is read through a separate *synchronous* SQLAlchemy engine on the same database
file (WAL: it sees committed data only), using the production row mapping.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from scrappy.application.jobs.model import JobId
from scrappy.infrastructure.persistence import create_engine, sqlite_url, upgrade_to_head
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence.job_queue import (
    _job_from,  # pyright: ignore[reportPrivateUsage]
)
from scrappy.infrastructure.persistence.tables import (
    extractions,
    jobs,
    offer_snapshots,
    offers,
    saved_searches,
    scrape_runs,
    search_offers,
)
from scrappy.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from tests.unit.fakes.store import StoreState


class SqlStore:
    def __init__(self, directory: Path | None = None) -> None:
        self._owned = directory is None
        self.directory = directory or Path(tempfile.mkdtemp(prefix="scrappy-sql-"))
        self.path = self.directory / "test.db"
        self.url = sqlite_url(self.path)
        upgrade_to_head(self.url)
        self.engine: AsyncEngine = create_engine(self.url)
        self._sync = create_sync_engine(f"sqlite:///{self.path.as_posix()}")

    def uow(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.engine)

    @property
    def state(self) -> StoreState:
        state = StoreState()
        with self._sync.connect() as conn:

            def rows(table):
                return conn.execute(select(table)).mappings().all()

            for row in rows(offers):
                offer = m.offer_from(row, offers.c)
                state.offers[offer.id] = offer
            for row in rows(offer_snapshots):
                state.snapshots.append(m.snapshot_from(row, offer_snapshots.c))
            for row in rows(saved_searches):
                search = m.search_from(row, saved_searches.c)
                state.searches[search.name] = search
            for row in rows(search_offers):
                link = m.link_from(row, search_offers.c)
                state.links[(link.search, link.offer_id)] = link
            for row in rows(extractions):
                state.extractions.append(m.extraction_from(row, extractions.c))
            for row in conn.execute(select(scrape_runs).order_by(scrape_runs.c.seq)).mappings():
                run = m.run_from(row, scrape_runs.c)
                state.runs[run.id] = run
            for row in conn.execute(select(jobs).order_by(jobs.c.seq)).mappings():
                job = _job_from(row, jobs.c)
                state.jobs[job.id] = job
                state.job_seq[JobId(job.id.value)] = row[jobs.c.seq]
                state.dedup_keys.add(job.dedup_key)
        return state

    async def close(self) -> None:
        await self.engine.dispose()
        self._sync.dispose()
        if self._owned:
            shutil.rmtree(self.directory, ignore_errors=True)

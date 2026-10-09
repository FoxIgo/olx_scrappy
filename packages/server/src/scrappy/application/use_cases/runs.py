"""Run lifecycle use cases: StartRun, ResumeRun, RefreshOffer."""

from __future__ import annotations

from dataclasses import dataclass

from scrappy.application.errors import NotFoundError
from scrappy.application.jobs.handlers.common import new_job
from scrappy.application.jobs.model import DiscoverPagePayload, EnrichOfferPayload
from scrappy.application.ports.listing_source import PageRef
from scrappy.application.ports.system import Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.finalize_run import FinalizeRun
from scrappy.domain.offer import OfferId
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SearchName
from scrappy.domain.shared import RunId


@dataclass(frozen=True, slots=True)
class StartRunResult:
    run: ScrapeRun
    created: bool
    """False when the search already had a RUNNING run, which is returned instead."""


class StartRun:
    """Create a ScrapeRun and its first DiscoverPage job; return immediately (ADR 0006).

    Idempotent per search: while a run is RUNNING, starting again returns that run, so any
    trigger (CLI, cron, agent) can retry safely (R2).
    """

    def __init__(self, *, uow: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    async def __call__(self, search_name: SearchName) -> StartRunResult:
        now = self._clock.now()
        async with self._uow() as uow:
            search = await uow.searches.get(search_name)
            if search is None:
                raise NotFoundError(f"search {search_name} not found")
            running = await uow.runs.find_running(search_name)
            if running is not None:
                return StartRunResult(running, created=False)

            run = ScrapeRun.start(RunId(self._ids.new_id()), search, now)
            search.mark_run_started(now)
            first_page = DiscoverPagePayload(search.name, PageRef.first(search.url))
            await uow.runs.save(run)
            await uow.searches.save(search)
            await uow.jobs.enqueue(new_job(self._ids, first_page, run_id=run.id, now=now))
            await uow.commit()
        return StartRunResult(run, created=True)


@dataclass(frozen=True, slots=True)
class ResumeRunResult:
    run: ScrapeRun
    requeued: int


class ResumeRun:
    """Continue a run where it stopped (R6): re-queue its FAILED (and orphaned RUNNING)
    jobs. Done work is not repeated: completed pages and offers keep their DONE jobs, and
    dedup keys stop them from being enqueued again."""

    def __init__(self, *, uow: UnitOfWorkFactory, clock: Clock, finalize_run: FinalizeRun) -> None:
        self._uow = uow
        self._clock = clock
        self._finalize_run = finalize_run

    async def __call__(self, run_id: RunId) -> ResumeRunResult:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                raise NotFoundError(f"run {run_id} not found")
            requeued = await uow.jobs.requeue_failed(run_id, now=self._clock.now())
            if requeued and not run.is_running:
                run.reopen()
                await uow.runs.save(run)
            await uow.commit()
        if run.is_running:
            run = await self._finalize_run(run_id)  # closes it if nothing is left to do
        return ResumeRunResult(run, requeued)


class RefreshOffer:
    """Explicitly re-fetch one offer page outside any run (R9). ``request_tag`` scopes the
    dedup key: the same tag twice enqueues once; use a new tag (e.g. a timestamp) for a new
    refresh. Works for ids never stored too (NOT_FOUND then stores nothing)."""

    def __init__(self, *, uow: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    async def __call__(self, offer_id: OfferId, request_tag: str | None = None) -> bool:
        now = self._clock.now()
        tag = request_tag or now.strftime("%Y%m%dT%H%M%S%f")
        async with self._uow() as uow:
            created = await uow.jobs.enqueue(
                new_job(self._ids, EnrichOfferPayload(offer_id, tag), run_id=None, now=now)
            )
            await uow.commit()
        return created

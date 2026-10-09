"""The worker loops against real SQLite with fakes (ADR 0010: scraper + extractor loop)."""

from __future__ import annotations

import asyncio

from scrappy.application.ports.listing_source import PageRef, SearchPageResult
from scrappy.domain.category import CategoryName
from scrappy.domain.run import RunStatus
from scrappy.domain.search import SearchName
from scrappy.domain.shared import RunId, SourceId
from scrappy.main import Container, build_app
from scrappy.presentation.worker import (
    WorkerRole,
    extract_until_idle,
    run_until_idle,
    run_worker,
    wait_for_run,
)
from tests.integration.cli.conftest import SEARCH_URL, CliEnv, scripted_source
from tests.unit.fakes import ScriptedListingSource


async def start(app: Container) -> RunId:
    await app.add_search(SearchName("s"), SourceId("olx_pl"), SEARCH_URL, CategoryName("laptop"))
    return (await app.start_run(SearchName("s"))).run.id


async def status_of(app: Container, run_id: RunId) -> RunStatus:
    async with app.uow() as uow:
        run = await uow.runs.get(run_id)
    assert run is not None
    return run.status


async def _count(app: Container) -> int:
    async with app.uow() as uow:
        offers = await uow.offers.list_with_content(after=None, limit=100)
        latest = await uow.extractions.latest_many([o.id for o in offers])
    return len(latest)


async def test_run_until_idle_scrapes_only_and_finalizes(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert await status_of(app, run_id) is RunStatus.RUNNING

        processed = await run_until_idle(app)

        assert processed == 1  # 1 discover page; extraction is not a job any more
        assert await status_of(app, run_id) is RunStatus.COMPLETED
        assert await app.extraction_status.backlog() == 4
        assert await run_until_idle(app) == 0  # idle: returns at once


async def test_run_until_idle_with_run_id_returns_once_the_run_finished(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert await run_until_idle(app, run_id, poll_interval=0.01) == 1
        assert await status_of(app, run_id) is RunStatus.COMPLETED


async def test_extract_until_idle_empties_the_backlog(env: CliEnv) -> None:
    async with await env.container() as app:
        await start(app)
        await run_until_idle(app)
        stats = await extract_until_idle(app)
        assert stats.stored == 4
        assert await app.extraction_status.backlog() == 0
        assert (await extract_until_idle(app)).stored == 0


async def test_run_worker_runs_both_loops_and_stops_on_request(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, poll_interval=0.01, reconcile_interval=0.01, probe=False)
        )

        run = await asyncio.wait_for(wait_for_run(app, run_id, poll_interval=0.01), timeout=20)
        assert run.status is RunStatus.COMPLETED
        for _ in range(500):  # the extractor loop reconciles afterwards
            if await _count(app) == 4:
                break
            await asyncio.sleep(0.01)

        stop.set()
        stats = await asyncio.wait_for(worker, timeout=5)
        assert stats.jobs == 1
        assert stats.extraction is not None and stats.extraction.stored == 4
        assert await app.extraction_status.backlog() == 0


async def test_worker_only_scrape_leaves_the_backlog(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, only=WorkerRole.SCRAPE, poll_interval=0.01)
        )
        await asyncio.wait_for(wait_for_run(app, run_id, poll_interval=0.01), timeout=20)
        stop.set()
        stats = await asyncio.wait_for(worker, timeout=5)
        assert stats.extraction is None
        assert await app.extraction_status.backlog() == 4


async def test_worker_only_extract_processes_an_existing_backlog(env: CliEnv) -> None:
    async with await env.container() as app:
        await start(app)
        await run_until_idle(app)
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, only=WorkerRole.EXTRACT, reconcile_interval=0.01, probe=False)
        )
        for _ in range(500):
            if await _count(app) == 4:
                break
            await asyncio.sleep(0.01)
        stop.set()
        stats = await asyncio.wait_for(worker, timeout=5)
        assert stats.jobs == 0
        assert stats.extraction is not None and stats.extraction.stored == 4


async def test_run_worker_stops_when_idle_even_without_work(env: CliEnv) -> None:
    async with await env.container() as app:
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, poll_interval=60, reconcile_interval=60, probe=False)
        )
        await asyncio.sleep(0.05)
        stop.set()  # wakes the long idle sleeps of both loops
        stats = await asyncio.wait_for(worker, timeout=5)
        assert stats.jobs == 0


class GatedSource(ScriptedListingSource):
    def __init__(self) -> None:
        super().__init__("olx_pl")
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch_search_page(self, page: PageRef) -> SearchPageResult:
        self.started.set()
        await self.release.wait()
        return await super().fetch_search_page(page)


async def test_cancellation_lets_the_running_job_finish(env: CliEnv) -> None:
    """Windows has no signal handlers in asyncio: Ctrl+C cancels the main task."""
    gated = GatedSource()
    scripted_source(gated)
    sources = {gated.source_id: gated}
    async with await build_app(env.settings, sources=sources, extractor=env.extractor) as app:
        run_id = await start(app)
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, poll_interval=0.01, reconcile_interval=0.01, probe=False)
        )
        await asyncio.wait_for(gated.started.wait(), timeout=10)

        worker.cancel()  # like Ctrl+C
        gated.release.set()
        stats = await asyncio.wait_for(worker, timeout=10)

        assert stop.is_set()
        assert stats.jobs == 1  # the in-flight discovery job completed, no more were claimed
        async with app.uow() as uow:
            jobs = await uow.jobs.list_for_run(run_id)
        statuses = {j.status.value for j in jobs}
        assert "running" not in statuses
        assert "done" in statuses


async def test_inline_run_recovers_a_job_orphaned_by_a_hard_kill(env: CliEnv) -> None:
    """Kill simulation: a job was claimed (RUNNING) by a worker that then died."""
    async with await env.container() as app:
        run_id = await start(app)
        assert len(await app.dispatcher.claim(limit=1)) == 1  # claimed, never completed

        assert await run_until_idle(app, run_id, poll_interval=0.01) == 1
        assert await status_of(app, run_id) is RunStatus.COMPLETED


async def test_worker_recovers_a_job_orphaned_by_a_hard_kill(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert len(await app.dispatcher.claim(limit=1)) == 1  # claimed, never completed
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(app, stop, only=WorkerRole.SCRAPE, poll_interval=0.01)
        )

        run = await asyncio.wait_for(wait_for_run(app, run_id, poll_interval=0.01), timeout=20)

        assert run.status is RunStatus.COMPLETED
        stop.set()
        assert (await asyncio.wait_for(worker, timeout=5)).jobs == 1

"""The worker loop against real SQLite with fakes."""

from __future__ import annotations

import asyncio

from scrappy.application.ports.listing_source import PageRef, SearchPageResult
from scrappy.domain.category import CategoryName
from scrappy.domain.run import RunStatus
from scrappy.domain.search import SearchName
from scrappy.domain.shared import RunId, SourceId
from scrappy.main import Container, build_app
from scrappy.presentation.worker import run_until_idle, run_worker, wait_for_run
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


async def test_run_until_idle_stops_when_the_queue_is_empty_and_finalizes(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert await status_of(app, run_id) is RunStatus.RUNNING

        processed = await run_until_idle(app)

        assert processed == 5  # 1 discover page + 4 extractions
        assert await status_of(app, run_id) is RunStatus.COMPLETED
        assert await run_until_idle(app) == 0  # idle: returns at once


async def test_run_until_idle_with_run_id_returns_once_the_run_finished(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert await run_until_idle(app, run_id, poll_interval=0.01) == 5
        assert await status_of(app, run_id) is RunStatus.COMPLETED


async def test_run_worker_processes_jobs_and_stops_on_request(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        stop = asyncio.Event()
        worker = asyncio.create_task(run_worker(app, stop, poll_interval=0.01))

        run = await asyncio.wait_for(wait_for_run(app, run_id, poll_interval=0.01), timeout=20)
        assert run.status is RunStatus.COMPLETED

        stop.set()
        assert await asyncio.wait_for(worker, timeout=5) == 5


async def test_run_worker_stops_when_idle_even_without_work(env: CliEnv) -> None:
    async with await env.container() as app:
        stop = asyncio.Event()
        worker = asyncio.create_task(run_worker(app, stop, poll_interval=60))
        await asyncio.sleep(0.05)
        stop.set()  # wakes the long idle sleep
        assert await asyncio.wait_for(worker, timeout=5) == 0


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
        worker = asyncio.create_task(run_worker(app, stop, poll_interval=0.01))
        await asyncio.wait_for(gated.started.wait(), timeout=10)

        worker.cancel()  # like Ctrl+C
        gated.release.set()
        processed = await asyncio.wait_for(worker, timeout=10)

        assert stop.is_set()
        assert processed == 1  # the in-flight discovery job completed, no more were claimed
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

        assert await run_until_idle(app, run_id, poll_interval=0.01) == 5
        assert await status_of(app, run_id) is RunStatus.COMPLETED


async def test_worker_recovers_a_job_orphaned_by_a_hard_kill(env: CliEnv) -> None:
    async with await env.container() as app:
        run_id = await start(app)
        assert len(await app.dispatcher.claim(limit=1)) == 1  # claimed, never completed
        stop = asyncio.Event()
        worker = asyncio.create_task(run_worker(app, stop, poll_interval=0.01))

        run = await asyncio.wait_for(wait_for_run(app, run_id, poll_interval=0.01), timeout=20)

        assert run.status is RunStatus.COMPLETED
        stop.set()
        assert await asyncio.wait_for(worker, timeout=5) == 5

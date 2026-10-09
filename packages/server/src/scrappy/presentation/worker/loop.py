"""The worker: two independent loops in one process (ADR 0010 section 1).

* **Scraper loop** (:func:`run_scraper`, ADR 0006): claim a job -> dispatch -> sleep when
  idle. Runs end when scraping ends; finalization is done by the dispatcher.
* **Extractor loop** (:func:`run_extractor`): reconcile ticks (claim backlog -> sync calls
  or a provider batch) and, while batches are open, poll ticks. It never waits for scraping.

:func:`run_worker` is ``scrappy worker``: both loops (or one, ``--only scrape|extract``)
until ``stop`` is set (SIGINT/SIGTERM). :func:`run_until_idle` is ``run --inline`` (scrape
only); :func:`extract_until_idle` is ``extract --inline``; :func:`wait_for_run` is
``run --wait``.

Graceful shutdown: a stop request lets the in-flight job finish, and lets the extractor
finish its current chunk of sync calls (the rest of the claimed chunk stays leased and
expires). A hard kill loses nothing: RUNNING jobs are re-queued at the next start (single
scraper assumption, ADR 0008) and extraction leases expire by time.

On Windows asyncio cannot install signal handlers; Ctrl+C cancels the main task, which is
turned into the same graceful stop. A second Ctrl+C aborts hard.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from scrappy.application.errors import NotFoundError
from scrappy.application.jobs.dispatcher import DispatchReport, DispatchStatus
from scrappy.application.use_cases.extraction import PollReport, ReconcileReport
from scrappy.domain.run import ScrapeRun
from scrappy.domain.shared import RunId
from scrappy.presentation.logging import get_logger
from scrappy.presentation.services import Services

log = get_logger("scrappy.worker")

type DispatchCallback = Callable[[DispatchReport], None]
type ExtractCallback = Callable[[ReconcileReport | PollReport], None]


class WorkerRole(StrEnum):
    SCRAPE = "scrape"
    EXTRACT = "extract"


@dataclass(slots=True)
class ExtractorStats:
    ticks: int = 0
    stored: int = 0
    failed: int = 0
    processed: int = 0
    """Offers claimed and settled by reconcile ticks (stored, failed, released, stale)."""
    batches_submitted: int = 0
    batches_finished: int = 0
    notes: list[str] = field(default_factory=list[str])
    unavailable: bool = False
    """The last tick had work but no profile could take it."""

    def add(self, report: ReconcileReport | PollReport) -> None:
        if isinstance(report, ReconcileReport):
            self.ticks += 1
            self.stored += report.stored
            self.failed += report.failed
            self.processed += report.processed
            self.batches_submitted += report.batches_submitted
            self.unavailable = report.unavailable
        else:
            self.stored += report.stored
            self.failed += report.item_failures
            self.batches_finished += report.completed + report.failed + report.expired
        for note in report.notes:
            if note not in self.notes:
                self.notes.append(note)


@dataclass(frozen=True, slots=True)
class WorkerStats:
    jobs: int = 0
    extraction: ExtractorStats | None = None


# ---------------------------------------------------------------------------- scraper


def _log_report(report: DispatchReport) -> None:
    job = report.job
    fields = {"job": str(job.id), "type": job.type.value, "attempt": job.attempts}
    if job.run_id is not None:
        fields["run"] = str(job.run_id)
    match report.status:
        case DispatchStatus.COMPLETED:
            log.info("job done", **fields)
        case DispatchStatus.RETRY_SCHEDULED:
            log.warning("job failed, will retry", error=report.error, **fields)
        case DispatchStatus.FAILED:
            log.error("job failed permanently", error=report.error, **fields)


async def _shielded[T](work: Awaitable[T], stop: asyncio.Event | None) -> T:
    """Await ``work`` so that a cancellation (Ctrl+C on Windows) lets it finish."""
    task = asyncio.ensure_future(work)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if stop is not None:
            stop.set()
        log.info("shutdown requested, finishing the current work")
        return await task


async def _step(
    app: Services, stop: asyncio.Event | None, on_dispatch: DispatchCallback | None
) -> bool:
    """Claim and run at most one job; return whether there was one."""
    jobs = await app.dispatcher.claim(limit=1)
    if not jobs:
        return False
    report = await _shielded(app.dispatcher.dispatch(jobs[0]), stop)
    _log_report(report)
    if on_dispatch:
        on_dispatch(report)
    return True


async def requeue_orphaned(app: Services) -> int:
    """Put RUNNING jobs left behind by a killed worker back to PENDING.

    Only valid under the single-worker assumption (see ``JobQueue.requeue_orphaned``)."""
    async with app.uow() as uow:
        count = await uow.jobs.requeue_orphaned(now=app.clock.now())
        await uow.commit()
    if count:
        log.warning("requeued orphaned jobs left RUNNING by a previous worker", count=count)
    return count


async def _start_scraper(app: Services) -> None:
    await requeue_orphaned(app)
    for run in await app.finalize_idle_runs():
        log.info("closed a run that had no work left", run=str(run.id), status=run.status.value)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_scraper(
    app: Services,
    stop: asyncio.Event,
    *,
    poll_interval: float | None = None,
    on_dispatch: DispatchCallback | None = None,
) -> int:
    """Process scraping jobs until ``stop`` is set. Returns the number of jobs processed."""
    interval = poll_interval if poll_interval is not None else app.worker_poll_interval
    processed = 0
    await _start_scraper(app)
    log.info("scraper loop started", poll_interval=interval)
    try:
        while not stop.is_set():
            if await _step(app, stop, on_dispatch):
                processed += 1
            else:
                await _sleep_or_stop(stop, interval)
    except asyncio.CancelledError:
        stop.set()  # cancelled while idle: nothing in flight
    log.info("scraper loop stopped", processed=processed)
    return processed


async def run_until_idle(
    app: Services,
    run_id: RunId | None = None,
    *,
    poll_interval: float = 0.5,
    stop: asyncio.Event | None = None,
    on_dispatch: DispatchCallback | None = None,
) -> int:
    """Run scraping jobs in-process. Returns the number of jobs processed.

    * ``run_id=None``: until no job is due (retries scheduled for later are left).
    * with ``run_id``: until that run is no longer RUNNING; when only delayed retries
      remain, wait for them (``poll_interval``) instead of returning early.
    """
    processed = 0
    stop = stop or asyncio.Event()
    await _start_scraper(app)
    while not stop.is_set():
        if await _step(app, stop, on_dispatch):
            processed += 1
            continue
        if run_id is None:
            break
        async with app.uow() as uow:
            unfinished = await uow.jobs.count_unfinished(run_id)
        if unfinished == 0:
            await app.finalize_run(run_id)  # normally done by the dispatcher; idempotent
            break
        await _sleep_or_stop(stop, poll_interval)  # delayed retries: wait for them
    return processed


# ---------------------------------------------------------------------------- extractor


async def _start_extractor(app: Services, *, probe: bool) -> None:
    """Recover interrupted batch submissions and check every profile of the chain."""
    report = await app.poll_batches(recover=True)
    for note in report.notes:
        log.info("batch recovery", note=note)
    selector = app.reconcile_extractions.selector
    for name in app.profiles.fallback:
        health = await selector.health(name, refresh=True, probe=probe)
        fields: dict[str, object] = {"profile": name, "detail": health.detail}
        if health.effective_structured_output is not None:
            fields["structured_output"] = health.effective_structured_output.value
        if health.ok:
            log.info("extraction profile ready", **fields)
        else:
            log.warning("extraction profile unavailable", **fields)


async def run_extractor(
    app: Services,
    stop: asyncio.Event,
    *,
    reconcile_interval: float | None = None,
    poll_interval: float | None = None,
    probe: bool = True,
    on_tick: ExtractCallback | None = None,
) -> ExtractorStats:
    """Reconcile the extraction backlog until ``stop`` is set."""
    policy = app.extraction_policy
    idle = (
        reconcile_interval
        if reconcile_interval is not None
        else policy.reconcile_interval.total_seconds()
    )
    poll_every = (
        poll_interval if poll_interval is not None else policy.poll_interval.total_seconds()
    )
    stats = ExtractorStats()
    loop = asyncio.get_running_loop()
    next_poll = 0.0
    try:
        await _start_extractor(app, probe=probe)
        log.info("extractor loop started", interval=idle, poll_interval=poll_every)
        while not stop.is_set():
            worked = False
            if loop.time() >= next_poll:
                polled = await _shielded(app.poll_batches(), stop)
                next_poll = loop.time() + poll_every
                stats.add(polled)
                worked = polled.did_work
                _log_extraction(polled)
                if on_tick:
                    on_tick(polled)
            if stop.is_set():
                break
            report = await _shielded(app.reconcile_extractions(stop=stop), stop)
            stats.add(report)
            _log_extraction(report)
            if on_tick:
                on_tick(report)
            if (report.did_work and not report.unavailable) or worked:
                continue
            await _sleep_or_stop(stop, max(0.0, min(idle, next_poll - loop.time())))
    except asyncio.CancelledError:
        stop.set()
    log.info("extractor loop stopped", stored=stats.stored, failed=stats.failed)
    return stats


def _log_extraction(report: ReconcileReport | PollReport) -> None:
    if isinstance(report, ReconcileReport):
        if report.did_work:
            log.info(
                "extraction tick",
                profile=report.profile,
                mode=report.mode,
                stored=report.stored,
                failed=report.failed,
                batches=report.batches_submitted,
            )
        if report.unavailable:
            log.warning("extraction backlog waits: no profile available", notes=report.notes)
    elif report.did_work:
        log.info(
            "batches polled",
            completed=report.completed,
            failed=report.failed,
            expired=report.expired,
            stored=report.stored,
        )


async def extract_until_idle(
    app: Services,
    *,
    profile: str | None = None,
    wait: bool = True,
    poll_interval: float | None = None,
    stop: asyncio.Event | None = None,
    on_tick: ExtractCallback | None = None,
    limit: int | None = None,
) -> ExtractorStats:
    """``scrappy extract --inline``: process the backlog in-process.

    Sync work runs until the backlog is empty (offers in backoff are left for later).
    Batches are submitted even below ``min_size``; with ``wait`` the open batches are
    polled until they finish, without it the call returns once they are submitted.
    ``limit`` caps how many offers are claimed in total.
    Stops early when no profile is available."""
    stop = stop or asyncio.Event()
    every = (
        poll_interval
        if poll_interval is not None
        else app.extraction_policy.poll_interval.total_seconds()
    )
    stats = ExtractorStats()
    await app.poll_batches(recover=True)
    while not stop.is_set():
        remaining = None if limit is None else limit - stats.processed
        if remaining is not None and remaining <= 0:
            break
        report = await _shielded(
            app.reconcile_extractions(profile=profile, flush=True, stop=stop, limit=remaining),
            stop,
        )
        stats.add(report)
        if on_tick:
            on_tick(report)
        if report.unavailable:
            break
        if report.did_work:
            continue
        if not wait or not await app.poll_batches.open_batches():
            break
        polled = await _shielded(app.poll_batches(), stop)
        stats.add(polled)
        if on_tick:
            on_tick(polled)
        if not polled.did_work:
            await _sleep_or_stop(stop, every)
    return stats


# ---------------------------------------------------------------------------- both


async def run_worker(
    app: Services,
    stop: asyncio.Event,
    *,
    only: WorkerRole | None = None,
    poll_interval: float | None = None,
    reconcile_interval: float | None = None,
    batch_poll_interval: float | None = None,
    probe: bool = True,
    on_dispatch: DispatchCallback | None = None,
) -> WorkerStats:
    """``scrappy worker``: the scraper and the extractor loop side by side until ``stop``."""
    scraper: asyncio.Task[int] | None = None
    extractor: asyncio.Task[ExtractorStats] | None = None
    if only in (None, WorkerRole.SCRAPE):
        scraper = asyncio.create_task(
            run_scraper(app, stop, poll_interval=poll_interval, on_dispatch=on_dispatch)
        )
    if only in (None, WorkerRole.EXTRACT):
        extractor = asyncio.create_task(
            run_extractor(
                app,
                stop,
                reconcile_interval=reconcile_interval,
                poll_interval=batch_poll_interval,
                probe=probe,
            )
        )
    tasks: list[asyncio.Task[int] | asyncio.Task[ExtractorStats]] = [
        t for t in (scraper, extractor) if t is not None
    ]
    log.info("worker started", loops=[r.value for r in WorkerRole if only in (None, r)])
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        if any(t.exception() is not None for t in done):
            stop.set()
    except asyncio.CancelledError:
        stop.set()  # Ctrl+C on Windows: graceful stop of both loops
    await asyncio.wait(tasks)
    for task in tasks:
        error = task.exception()
        if error is not None:
            raise error
    jobs = scraper.result() if scraper is not None else 0
    extraction = extractor.result() if extractor is not None else None
    log.info("worker stopped", jobs=jobs)
    return WorkerStats(jobs, extraction)


async def wait_for_run(
    app: Services,
    run_id: RunId,
    *,
    poll_interval: float = 2.0,
    on_poll: Callable[[ScrapeRun, int], None] | None = None,
) -> ScrapeRun:
    """Poll until the run is finished (executed by a separate worker process)."""
    while True:
        async with app.uow() as uow:
            run = await uow.runs.get(run_id)
            unfinished = await uow.jobs.count_unfinished(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        if not run.is_running:
            return run
        if on_poll:
            on_poll(run, unfinished)
        await asyncio.sleep(poll_interval)

"""The worker loop (ADR 0006): claim -> dispatch -> sleep when idle.

* :func:`run_worker` is ``scrappy worker``: runs until ``stop`` is set (SIGINT/SIGTERM).
* :func:`run_until_idle` is ``--inline``: the same loop, in-process, until the queue is
  idle, or (with a ``run_id``) until that run has finished.
* :func:`wait_for_run` is ``run --wait``: only watches a run that another worker executes.

Finalization (run status, metrics, health) is **not** triggered here: ``JobDispatcher.dispatch``
calls ``FinalizeRun`` after every final job outcome, and ``ResumeRun`` does it for a run with
nothing left to do. The loop only has to keep dispatching.

Both ``run_worker`` and ``run_until_idle`` first requeue RUNNING jobs (single-worker
assumption, ADR 0008): a hard-killed worker leaves them behind and nobody else owns them.

Jobs are claimed one at a time so that a shutdown request never leaves claimed-but-unrun
jobs in RUNNING state. A request during a job lets that job finish (graceful); a second
Ctrl+C aborts hard.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from scrappy.application.errors import NotFoundError
from scrappy.application.jobs.dispatcher import DispatchReport, DispatchStatus
from scrappy.domain.run import ScrapeRun
from scrappy.domain.shared import RunId
from scrappy.presentation.logging import get_logger
from scrappy.presentation.services import Services

log = get_logger("scrappy.worker")

type DispatchCallback = Callable[[DispatchReport], None]


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


async def _step(
    app: Services, stop: asyncio.Event | None, on_dispatch: DispatchCallback | None
) -> bool:
    """Claim and run at most one job; return whether there was one. A cancellation (Ctrl+C
    on Windows, where asyncio cannot install signal handlers) lets the running job finish."""
    jobs = await app.dispatcher.claim(limit=1)
    if not jobs:
        return False
    task = asyncio.ensure_future(app.dispatcher.dispatch(jobs[0]))
    try:
        report = await asyncio.shield(task)
    except asyncio.CancelledError:
        if stop is not None:
            stop.set()
        log.info("shutdown requested, finishing the current job")
        report = await task
        _log_report(report)
        if on_dispatch:
            on_dispatch(report)
        return True
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


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_worker(
    app: Services,
    stop: asyncio.Event,
    *,
    poll_interval: float | None = None,
    on_dispatch: DispatchCallback | None = None,
) -> int:
    """Process jobs until ``stop`` is set. Returns the number of jobs processed."""
    interval = poll_interval if poll_interval is not None else app.worker_poll_interval
    processed = 0
    await requeue_orphaned(app)
    log.info("worker started", poll_interval=interval, extraction=app.has_extractor)
    try:
        while not stop.is_set():
            if await _step(app, stop, on_dispatch):
                processed += 1
            else:
                await _sleep_or_stop(stop, interval)
    except asyncio.CancelledError:
        pass  # cancelled while idle: nothing in flight
    log.info("worker stopped", processed=processed)
    return processed


async def run_until_idle(
    app: Services,
    run_id: RunId | None = None,
    *,
    poll_interval: float = 0.5,
    stop: asyncio.Event | None = None,
    on_dispatch: DispatchCallback | None = None,
) -> int:
    """Run jobs in-process. Returns the number of jobs processed.

    * ``run_id=None``: until no job is due (retries scheduled for later are left).
    * with ``run_id``: until that run is no longer RUNNING; when only delayed retries
      remain, wait for them (``poll_interval``) instead of returning early.
    """
    processed = 0
    stop = stop or asyncio.Event()
    await requeue_orphaned(app)
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

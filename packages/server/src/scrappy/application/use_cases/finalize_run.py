"""FinalizeRun: when a run has no unfinished jobs, aggregate metrics and set its status."""

from __future__ import annotations

from scrappy.application.errors import NotFoundError
from scrappy.application.jobs.model import JobStatus
from scrappy.application.policy import PipelinePolicy
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.domain.run import RunMetrics, ScrapeRun, conclude_run
from scrappy.domain.shared import RunId

MAX_ERRORS = 20


class FinalizeRun:
    """Idempotent completion check (ADR 0005, ADR 0006).

    Called by the dispatcher after every job of a run, and by ``ResumeRun``. Does nothing
    while the run still has PENDING/RUNNING jobs or is already finished. Metrics are the
    sum of the stored job results, so the outcome does not depend on how often jobs ran.
    """

    def __init__(self, *, uow: UnitOfWorkFactory, clock: Clock, policy: PipelinePolicy) -> None:
        self._uow = uow
        self._clock = clock
        self._policy = policy

    async def __call__(self, run_id: RunId) -> ScrapeRun:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                raise NotFoundError(f"run {run_id} not found")
            if not run.is_running or await uow.jobs.count_unfinished(run_id) > 0:
                return run

            jobs = await uow.jobs.list_for_run(run_id)
            metrics = RunMetrics()
            failures: dict[tuple[str, str | None], list[str]] = {}  # (type, error) -> job keys
            for job in jobs:
                if job.result is not None:
                    metrics = metrics + job.result.metrics
                if job.status is JobStatus.FAILED:
                    metrics = metrics + RunMetrics(failed_jobs=1)
                    failures.setdefault((job.type.value, job.last_error), []).append(job.dedup_key)

            errors = [
                f"{kind} {keys[0]}: {error}"
                if len(keys) == 1
                else f"{kind} x{len(keys)} (e.g. {keys[0]}): {error}"
                for (kind, error), keys in failures.items()
            ][:MAX_ERRORS]

            conclusion = conclude_run(metrics, self._policy.health.for_source(run.source))
            run.finish(conclusion, metrics, self._clock.now(), tuple(errors))
            await uow.runs.save(run)
            await uow.commit()
            return run

"""JobDispatcher: claim jobs, route them to handlers, record the outcome (ADR 0006).

The worker loop (polling, sleeping, signals) is presentation; it calls
:meth:`JobDispatcher.run_once` repeatedly. ``--inline`` mode does the same in-process.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from scrappy.application.jobs.errors import PermanentJobError, RetryableJobError
from scrappy.application.jobs.model import Job, JobResult, JobType
from scrappy.application.policy import RetryPolicy
from scrappy.application.ports.system import Clock
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.finalize_run import FinalizeRun


class JobHandler(Protocol):
    async def handle(self, job: Job) -> JobResult:
        """Do the job; return its contribution to run metrics.

        Raise :class:`RetryableJobError` / :class:`PermanentJobError` when it cannot be
        completed. Any other exception is treated as retryable. Must be idempotent.
        """
        ...


class DispatchStatus(StrEnum):
    COMPLETED = "completed"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DispatchReport:
    job: Job
    status: DispatchStatus
    error: str | None = None


class JobDispatcher:
    def __init__(
        self,
        *,
        handlers: Mapping[JobType, JobHandler],
        uow: UnitOfWorkFactory,
        clock: Clock,
        retry: RetryPolicy,
        finalize_run: FinalizeRun,
    ) -> None:
        self._handlers = dict(handlers)
        self._uow = uow
        self._clock = clock
        self._retry = retry
        self._finalize_run = finalize_run

    async def claim(self, types: Collection[JobType] = (), limit: int = 1) -> list[Job]:
        types = types or tuple(self._handlers)
        async with self._uow() as uow:
            jobs = await uow.jobs.claim(types, limit=limit, now=self._clock.now())
            await uow.commit()
        return jobs

    async def dispatch(self, job: Job) -> DispatchReport:
        """Run one claimed job and record DONE / retry / FAILED, then check its run."""
        handler = self._handlers.get(job.type)
        report: DispatchReport
        try:
            if handler is None:
                raise PermanentJobError(f"no handler registered for {job.type.value}")
            result = await handler.handle(job)
        except PermanentJobError as error:
            report = await self._fail(job, error.message, None, error.result, permanent=True)
        except RetryableJobError as error:
            report = await self._fail(job, error.message, error.retry_after, error.result)
        except Exception as error:  # any handler crash is a retryable failure
            report = await self._fail(job, f"{type(error).__name__}: {error}", None, None)
        else:
            async with self._uow() as uow:
                await uow.jobs.complete(job.id, result, now=self._clock.now())
                await uow.commit()
            report = DispatchReport(job, DispatchStatus.COMPLETED)

        if job.run_id is not None and report.status is not DispatchStatus.RETRY_SCHEDULED:
            await self._finalize_run(job.run_id)
        return report

    async def run_once(self, types: Collection[JobType] = (), limit: int = 1) -> int:
        """Claim up to ``limit`` due jobs and dispatch them sequentially; return the count."""
        jobs = await self.claim(types, limit)
        for job in jobs:
            await self.dispatch(job)
        return len(jobs)

    async def _fail(
        self,
        job: Job,
        error: str,
        retry_after: timedelta | None,
        result: JobResult | None,
        *,
        permanent: bool = False,
    ) -> DispatchReport:
        now = self._clock.now()
        retry_at = None if permanent else self._retry.retry_at(job.attempts, now, retry_after)
        async with self._uow() as uow:
            await uow.jobs.fail(job.id, error=error, retry_at=retry_at, result=result, now=now)
            await uow.commit()
        status = DispatchStatus.RETRY_SCHEDULED if retry_at else DispatchStatus.FAILED
        return DispatchReport(job, status, error)

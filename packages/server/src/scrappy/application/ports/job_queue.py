"""``JobQueue``: durable work items of the pipeline (ADR 0006, R6, R13).

Contract for adapter authors
----------------------------
* **Transactions.** The queue is reached through ``UnitOfWork.jobs`` and takes part in the
  same transaction as the repositories: follow-up jobs are enqueued atomically with the
  state change that caused them. Nothing is visible to other units of work before commit.
* **Dedup.** ``dedup_key`` is unique across *all* jobs ever stored, whatever their status
  (a UNIQUE index + ``INSERT ... ON CONFLICT DO NOTHING`` in SQL). Keys carry their own
  scope (run, content hash, request tag); see :mod:`scrappy.application.jobs.model`.
* **Ordering.** ``claim`` returns PENDING jobs with ``available_at <= now``, oldest
  ``available_at`` first, ties broken by insertion order (FIFO).
* **Delivery.** At-least-once. Handlers are idempotent; a job may run twice.
* **Concurrency.** ``claim`` must not hand the same job to two callers that commit
  (SQLite: single writer + the claim's UPDATE in one transaction; Postgres: ``FOR UPDATE
  SKIP LOCKED``).
* Methods addressing a job by id raise ``KeyError`` for an unknown id.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from scrappy.application.jobs.model import Job, JobId, JobResult, JobType
from scrappy.domain.shared import RunId


class JobQueue(Protocol):
    async def enqueue(self, job: Job) -> bool:
        """Store a new PENDING job. Returns ``False`` (and stores nothing) if a job with the
        same ``dedup_key`` already exists in any status."""
        ...

    async def claim(self, types: Collection[JobType], *, limit: int, now: datetime) -> list[Job]:
        """Atomically move up to ``limit`` due PENDING jobs of the given types to RUNNING,
        incrementing ``attempts``; return them as updated. Empty ``types`` means all."""
        ...

    async def complete(self, job_id: JobId, result: JobResult, *, now: datetime) -> None:
        """Mark DONE, store ``result``, set ``finished_at``. Completing a DONE job again
        overwrites the result (idempotent)."""
        ...

    async def fail(
        self,
        job_id: JobId,
        *,
        error: str,
        retry_at: datetime | None,
        result: JobResult | None = None,
        now: datetime,
    ) -> None:
        """Record ``error`` as ``last_error``. With ``retry_at``: back to PENDING with
        ``available_at = retry_at`` (attempts kept). Without: FAILED for good, with
        ``result`` stored and ``finished_at`` set."""
        ...

    async def get(self, job_id: JobId) -> Job | None: ...

    async def count_unfinished(self, run_id: RunId) -> int:
        """Number of PENDING or RUNNING jobs of the run (the run is done at zero)."""
        ...

    async def list_for_run(self, run_id: RunId) -> list[Job]:
        """All jobs of the run in insertion order (used to aggregate run metrics)."""
        ...

    async def requeue_failed(self, run_id: RunId, *, now: datetime) -> int:
        """Resume support (R6): move the run's FAILED and RUNNING jobs back to PENDING
        (``attempts = 0``, ``available_at = now``, result cleared). Returns the count.
        RUNNING jobs are included because after a crash nobody owns them; resume a run
        only while no worker is processing it (or accept a duplicate execution)."""
        ...

    async def requeue_orphaned(self, *, now: datetime) -> int:
        """Crash recovery: move **every** RUNNING job (any run) back to PENDING with
        ``available_at = now``. ``attempts`` is kept, so a job that keeps killing the worker
        still runs out of attempts; result and ``last_error`` are untouched. Returns the count.

        Single-worker assumption (ADR 0008, open issue 1): called once at worker startup,
        when nobody can own a RUNNING job any more. With several workers this would steal
        jobs from live ones; that future needs leases with heartbeat/expiry instead."""
        ...

"""SQL job queue (``JobQueue`` port): durable pipeline work items in the ``jobs`` table.

* **Dedup forever**: ``dedup_key`` has a UNIQUE index; ``enqueue`` is
  ``INSERT ... ON CONFLICT (dedup_key) DO NOTHING`` and reports whether a row was inserted.
* **FIFO**: ``claim`` orders by ``(available_at, seq)``; ``seq`` is the insertion counter.
* **Atomic claim**: select candidate ids with ``FOR UPDATE SKIP LOCKED`` (a no-op that
  SQLAlchemy omits on SQLite, whose ``BEGIN IMMEDIATE`` transactions are already serialised
  by the single writer lock; on PostgreSQL it lets concurrent workers take disjoint jobs),
  then flip them to RUNNING with ``attempts + 1`` in the same transaction. The UPDATE
  re-checks ``status = 'pending'`` as a second guard.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from scrappy.application.jobs.codec import (
    decode_payload,
    decode_result,
    encode_payload,
    encode_result,
)
from scrappy.application.jobs.model import Job, JobId, JobResult, JobStatus, JobType
from scrappy.domain.shared import RunId
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence._sql import insert_ignore
from scrappy.infrastructure.persistence.tables import jobs


def _job_from(row: m.Row, c: m.Cols) -> Job:
    run_id = row[c.run_id]
    result = row[c.result]
    return Job(
        id=JobId(row[c.id]),
        payload=decode_payload(JobType(row[c.type]), row[c.payload]),
        dedup_key=row[c.dedup_key],
        run_id=None if run_id is None else RunId(run_id),
        created_at=row[c.created_at],
        available_at=row[c.available_at],
        status=JobStatus(row[c.status]),
        attempts=row[c.attempts],
        last_error=row[c.last_error],
        result=None if result is None else decode_result(result),
        finished_at=row[c.finished_at],
    )


class SqlJobQueue:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def enqueue(self, job: Job) -> bool:
        values: dict[str, Any] = {
            "id": job.id.value,
            "type": job.type.value,
            "payload": encode_payload(job.payload),
            "status": JobStatus.PENDING.value,
            "attempts": job.attempts,
            "dedup_key": job.dedup_key,
            "run_id": None if job.run_id is None else job.run_id.value,
            "created_at": job.created_at,
            "available_at": job.available_at,
            "finished_at": job.finished_at,
            "result": None if job.result is None else encode_result(job.result),
            "last_error": job.last_error,
        }
        # A clash on ``id`` (not on the dedup key) is a programming error and raises
        # IntegrityError, like the in-memory queue's ValueError for a reused id.
        return await insert_ignore(self._conn, jobs, values, ["dedup_key"])

    async def claim(self, types: Collection[JobType], *, limit: int, now: datetime) -> list[Job]:
        if limit < 1:
            return []
        due = [jobs.c.status == JobStatus.PENDING.value, jobs.c.available_at <= now]
        if types:
            due.append(jobs.c.type.in_(sorted(t.value for t in types)))
        order = (jobs.c.available_at, jobs.c.seq)
        pick = (
            select(jobs.c.seq)
            .where(*due)
            .order_by(*order)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        seqs = [row[0] for row in (await self._conn.execute(pick)).all()]
        if not seqs:
            return []
        await self._conn.execute(
            update(jobs)
            .where(jobs.c.seq.in_(seqs), jobs.c.status == JobStatus.PENDING.value)
            .values(status=JobStatus.RUNNING.value, attempts=jobs.c.attempts + 1)
        )
        stmt = select(jobs).where(jobs.c.seq.in_(seqs)).order_by(*order)
        return [_job_from(row, jobs.c) for row in (await self._conn.execute(stmt)).mappings()]

    async def complete(self, job_id: JobId, result: JobResult, *, now: datetime) -> None:
        await self._update_one(
            job_id,
            status=JobStatus.DONE.value,
            result=encode_result(result),
            finished_at=now,
        )

    async def fail(
        self,
        job_id: JobId,
        *,
        error: str,
        retry_at: datetime | None,
        result: JobResult | None = None,
        now: datetime,
    ) -> None:
        if retry_at is not None:
            await self._update_one(
                job_id, status=JobStatus.PENDING.value, available_at=retry_at, last_error=error
            )
        else:
            await self._update_one(
                job_id,
                status=JobStatus.FAILED.value,
                last_error=error,
                result=None if result is None else encode_result(result),
                finished_at=now,
            )

    async def get(self, job_id: JobId) -> Job | None:
        row = (
            (await self._conn.execute(select(jobs).where(jobs.c.id == job_id.value)))
            .mappings()
            .first()
        )
        return None if row is None else _job_from(row, jobs.c)

    async def count_unfinished(self, run_id: RunId) -> int:
        unfinished = [JobStatus.PENDING.value, JobStatus.RUNNING.value]
        stmt = select(jobs.c.seq).where(
            jobs.c.run_id == run_id.value, jobs.c.status.in_(unfinished)
        )
        return len((await self._conn.execute(stmt)).all())

    async def list_for_run(self, run_id: RunId) -> list[Job]:
        stmt = select(jobs).where(jobs.c.run_id == run_id.value).order_by(jobs.c.seq)
        return [_job_from(row, jobs.c) for row in (await self._conn.execute(stmt)).mappings()]

    async def requeue_failed(self, run_id: RunId, *, now: datetime) -> int:
        result = await self._conn.execute(
            update(jobs)
            .where(
                jobs.c.run_id == run_id.value,
                jobs.c.status.in_([JobStatus.FAILED.value, JobStatus.RUNNING.value]),
            )
            .values(
                status=JobStatus.PENDING.value,
                attempts=0,
                available_at=now,
                result=None,
                finished_at=None,
            )
        )
        return cast("CursorResult[Any]", result).rowcount

    async def requeue_orphaned(self, *, now: datetime) -> int:
        result = await self._conn.execute(
            update(jobs)
            .where(jobs.c.status == JobStatus.RUNNING.value)
            .values(status=JobStatus.PENDING.value, available_at=now)
        )
        return cast("CursorResult[Any]", result).rowcount

    async def _update_one(self, job_id: JobId, **values: Any) -> None:
        result = await self._conn.execute(
            update(jobs).where(jobs.c.id == job_id.value).values(**values)
        )
        if cast("CursorResult[Any]", result).rowcount == 0:
            raise KeyError(job_id)

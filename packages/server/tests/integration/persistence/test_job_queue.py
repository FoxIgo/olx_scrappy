"""SqlJobQueue: dedup forever, FIFO claim, attempts, retries, resume, atomic claim."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest

from scrappy.application.jobs.model import (
    DiscoverPagePayload,
    EnrichOfferPayload,
    ExtractOfferPayload,
    Job,
    JobId,
    JobPayload,
    JobResult,
    JobStatus,
    JobType,
)
from scrappy.application.ports.listing_source import PageRef
from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash
from scrappy.domain.run import PhaseMetrics, RunMetrics
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, RunId
from tests.unit.builders import T0, oid

type Factory = Callable[[], UnitOfWork]

RUN = RunId("run1")
HASH = ContentHash("c" * 64)
DISCOVER = DiscoverPagePayload(SearchName("s"), PageRef("https://x.test/?page=2", 2))


def job(job_id: str, payload: JobPayload | None = None, minutes: int = 0, run: RunId | None = RUN):
    payload = payload or EnrichOfferPayload(oid(job_id))
    return Job.new(JobId(job_id), payload, run_id=run, now=T0 + timedelta(minutes=minutes))


async def put(uow: Factory, *jobs: Job) -> None:
    async with uow() as unit:
        for j in jobs:
            await unit.jobs.enqueue(j)
        await unit.commit()


async def test_dedup_is_forever_across_statuses_and_units(uow: Factory) -> None:
    async with uow() as unit:
        assert await unit.jobs.enqueue(job("j1", EnrichOfferPayload(oid("1"))))
        assert not await unit.jobs.enqueue(job("j2", EnrichOfferPayload(oid("1"))))
        await unit.commit()
    async with uow() as unit:
        (claimed,) = await unit.jobs.claim([], limit=10, now=T0)
        assert claimed.id == JobId("j1")
        assert not await unit.jobs.enqueue(job("j3", EnrichOfferPayload(oid("1"))))  # RUNNING
        await unit.jobs.complete(claimed.id, JobResult(), now=T0)
        assert not await unit.jobs.enqueue(job("j4", EnrichOfferPayload(oid("1"))))  # DONE
        await unit.commit()
    async with uow() as unit:
        assert await unit.jobs.get(JobId("j2")) is None
        assert await unit.jobs.enqueue(job("j5", EnrichOfferPayload(oid("2"))))


async def test_reused_job_id_with_a_new_key_is_an_error(uow: Factory) -> None:
    await put(uow, job("same"))
    async with uow() as unit:
        with pytest.raises(Exception, match=r"(?i)unique"):
            await unit.jobs.enqueue(job("same", EnrichOfferPayload(oid("other"))))


async def test_payloads_and_fields_round_trip(uow: Factory) -> None:
    payloads: list[JobPayload] = [
        DISCOVER,
        EnrichOfferPayload(oid("1")),
        EnrichOfferPayload(oid("1"), request_tag="t"),
        ExtractOfferPayload(oid("1"), HASH, "cat1"),
        ExtractOfferPayload(oid("1"), HASH, "cat1", force=True, request_tag="v3"),
    ]
    jobs = [
        job(f"j{i}", p, run=None if isinstance(p, EnrichOfferPayload) and p.request_tag else RUN)
        for i, p in enumerate(payloads)
    ]
    await put(uow, *jobs)
    async with uow() as unit:
        for original in jobs:
            loaded = await unit.jobs.get(original.id)
            assert loaded == original
            assert loaded.type is original.type if loaded else False


async def test_claim_is_fifo_by_available_at_then_insertion(uow: Factory) -> None:
    await put(
        uow,
        job("late", minutes=5),
        job("b", minutes=0),
        job("a", minutes=0),
        job("early", minutes=-1),
    )
    async with uow() as unit:
        claimed = await unit.jobs.claim([], limit=10, now=T0 + timedelta(minutes=5))
        assert [j.id.value for j in claimed] == ["early", "b", "a", "late"]
        assert all(j.status is JobStatus.RUNNING and j.attempts == 1 for j in claimed)


async def test_claim_respects_due_time_types_and_limit(uow: Factory) -> None:
    await put(
        uow,
        job("e1", EnrichOfferPayload(oid("1"))),
        job("x1", ExtractOfferPayload(oid("1"), HASH, "c"), minutes=3),
        job("d1", DISCOVER),
        job("e2", EnrichOfferPayload(oid("2"))),
    )
    async with uow() as unit:
        assert await unit.jobs.claim([JobType.EXTRACT_OFFER], limit=5, now=T0) == []
        (extract,) = await unit.jobs.claim(
            [JobType.EXTRACT_OFFER], limit=5, now=T0 + timedelta(minutes=3)
        )
        assert extract.id == JobId("x1")
        first = await unit.jobs.claim([JobType.ENRICH_OFFER], limit=1, now=T0)
        assert [j.id.value for j in first] == ["e1"]
        rest = await unit.jobs.claim([JobType.ENRICH_OFFER, JobType.DISCOVER_PAGE], limit=9, now=T0)
        assert sorted(j.id.value for j in rest) == ["d1", "e2"]
        assert await unit.jobs.claim([], limit=9, now=T0) == []
        assert await unit.jobs.claim([], limit=0, now=T0) == []
        await unit.commit()


async def test_claim_is_visible_only_after_commit(uow: Factory) -> None:
    await put(uow, job("j"))
    async with uow() as unit:
        assert len(await unit.jobs.claim([], limit=1, now=T0)) == 1
    async with uow() as unit:  # rolled back: claimable again, attempts untouched
        (again,) = await unit.jobs.claim([], limit=1, now=T0)
        assert again.attempts == 1


async def test_concurrent_claims_never_share_a_job(uow: Factory) -> None:
    await put(uow, *[job(f"j{i:02d}") for i in range(20)])

    async def worker() -> list[str]:
        claimed: list[str] = []
        while True:
            async with uow() as unit:
                batch = await unit.jobs.claim([], limit=3, now=T0)
                await unit.commit()
            if not batch:
                return claimed
            claimed.extend(j.id.value for j in batch)

    results = await asyncio.gather(*[worker() for _ in range(4)])
    everything = [i for r in results for i in r]
    assert sorted(everything) == [f"j{i:02d}" for i in range(20)]  # each exactly once


async def test_complete_stores_result_and_is_idempotent(uow: Factory) -> None:
    await put(uow, job("j"))
    metrics = RunMetrics(
        enrichment=PhaseMetrics(accepted=1, outcomes={FetchOutcome.OK: 1}),
        usage=TokenUsage(3, 4, Decimal("0.5")),
    )
    done_at = T0 + timedelta(minutes=2)
    async with uow() as unit:
        (claimed,) = await unit.jobs.claim([], limit=1, now=T0)
        await unit.jobs.complete(claimed.id, JobResult(metrics, ("note",)), now=done_at)
        await unit.jobs.complete(claimed.id, JobResult(metrics, ("again",)), now=done_at)
        await unit.commit()
    async with uow() as unit:
        done = await unit.jobs.get(JobId("j"))
    assert done is not None
    assert done.status is JobStatus.DONE and done.finished_at == done_at
    assert done.result == JobResult(metrics, ("again",))
    assert done.attempts == 1


async def test_fail_with_retry_is_not_claimable_before_retry_at(uow: Factory) -> None:
    await put(uow, job("j"))
    retry_at = T0 + timedelta(minutes=10)
    async with uow() as unit:
        (claimed,) = await unit.jobs.claim([], limit=1, now=T0)
        await unit.jobs.fail(claimed.id, error="403", retry_at=retry_at, now=T0)
        await unit.commit()
    async with uow() as unit:
        retried = await unit.jobs.get(JobId("j"))
        assert retried is not None
        assert (retried.status, retried.available_at, retried.attempts, retried.last_error) == (
            JobStatus.PENDING,
            retry_at,
            1,
            "403",
        )
        assert retried.finished_at is None
        assert await unit.jobs.count_unfinished(RUN) == 1
        assert await unit.jobs.claim([], limit=1, now=retry_at - timedelta(seconds=1)) == []
        (again,) = await unit.jobs.claim([], limit=1, now=retry_at)
        assert again.attempts == 2


async def test_permanent_fail_stores_result_and_requeue_resets(uow: Factory) -> None:
    await put(uow, job("bad"), job("running"), job("ok"), job("other-run", run=RunId("run2")))
    result = JobResult(RunMetrics(failed_jobs=1), ("gave up",))
    async with uow() as unit:
        claimed = await unit.jobs.claim([], limit=3, now=T0)  # bad, running, ok
        by_id = {j.id.value: j for j in claimed}
        await unit.jobs.fail(by_id["bad"].id, error="boom", retry_at=None, result=result, now=T0)
        await unit.jobs.complete(by_id["ok"].id, JobResult(), now=T0)
        await unit.commit()
    async with uow() as unit:
        failed = await unit.jobs.get(JobId("bad"))
        assert failed is not None
        assert failed.status is JobStatus.FAILED and failed.result == result
        assert failed.finished_at == T0 and failed.last_error == "boom"
        assert await unit.jobs.count_unfinished(RUN) == 1  # "running"
        later = T0 + timedelta(hours=1)
        assert await unit.jobs.requeue_failed(RUN, now=later) == 2  # FAILED + RUNNING
        for job_id in ("bad", "running"):
            requeued = await unit.jobs.get(JobId(job_id))
            assert requeued is not None
            assert (requeued.status, requeued.attempts, requeued.available_at) == (
                JobStatus.PENDING,
                0,
                later,
            )
            assert requeued.result is None and requeued.finished_at is None
        done = await unit.jobs.get(JobId("ok"))
        assert done is not None and done.status is JobStatus.DONE
        other = await unit.jobs.get(JobId("other-run"))
        assert other is not None and other.status is JobStatus.PENDING
        assert await unit.jobs.count_unfinished(RUN) == 2
        assert await unit.jobs.count_unfinished(RunId("run2")) == 1
        assert await unit.jobs.count_unfinished(RunId("unknown")) == 0


async def test_list_for_run_is_in_insertion_order(uow: Factory) -> None:
    await put(uow, job("c", minutes=9), job("a"), job("x", run=RunId("run2")), job("b"))
    async with uow() as unit:
        assert [j.id.value for j in await unit.jobs.list_for_run(RUN)] == ["c", "a", "b"]
        assert await unit.jobs.list_for_run(RunId("nobody")) == []


async def test_unknown_job_id_raises_key_error(uow: Factory) -> None:
    ghost = JobId("ghost")
    async with uow() as unit:
        assert await unit.jobs.get(ghost) is None
        with pytest.raises(KeyError):
            await unit.jobs.complete(ghost, JobResult(), now=T0)
        with pytest.raises(KeyError):
            await unit.jobs.fail(ghost, error="x", retry_at=None, now=T0)
        with pytest.raises(KeyError):
            await unit.jobs.fail(ghost, error="x", retry_at=T0, now=T0)


async def test_requeue_orphaned_resets_running_jobs_of_any_run_keeping_attempts(
    uow: Factory,
) -> None:
    await put(uow, job("a"), job("b"), job("c"), job("d", run=RunId("run2")), job("e"))
    async with uow() as unit:
        claimed = await unit.jobs.claim([], limit=4, now=T0)  # a, b, c, d
        await unit.jobs.complete(claimed[2].id, JobResult(), now=T0)  # c is DONE
        await unit.commit()
    later = T0 + timedelta(hours=1)
    async with uow() as unit:
        assert await unit.jobs.requeue_orphaned(now=later) == 3  # a, b, d
        await unit.commit()
    async with uow() as unit:
        for job_id in ("a", "b", "d"):
            requeued = await unit.jobs.get(JobId(job_id))
            assert requeued is not None
            assert (requeued.status, requeued.attempts, requeued.available_at) == (
                JobStatus.PENDING,
                1,
                later,
            )
        done = await unit.jobs.get(JobId("c"))
        assert done is not None and done.status is JobStatus.DONE
        assert await unit.jobs.requeue_orphaned(now=later) == 0
        reclaimed = {j.id.value: j for j in await unit.jobs.claim([], limit=10, now=later)}
        assert reclaimed["a"].attempts == 2
        assert reclaimed["e"].attempts == 1

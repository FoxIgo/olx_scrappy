"""Job model, dedup keys, codec round-trips and the reference queue behaviour."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from scrappy.application.jobs.codec import (
    decode_metrics,
    decode_payload,
    decode_result,
    encode_metrics,
    encode_payload,
    encode_result,
)
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
    dedup_key,
)
from scrappy.application.policy import RetryPolicy
from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.extraction import TokenUsage
from scrappy.domain.offer import ContentHash
from scrappy.domain.run import DiscoveryCoverage, PhaseMetrics, RunMetrics
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId
from tests.unit.builders import T0, oid
from tests.unit.fakes import InMemoryStore

RUN = RunId("run1")
HASH = ContentHash("a" * 64)
PAYLOADS: list[JobPayload] = [
    DiscoverPagePayload(SearchName("s"), PageRef("https://x.test/?page=2", 2)),
    EnrichOfferPayload(oid("1")),
    EnrichOfferPayload(oid("1"), request_tag="t"),
    ExtractOfferPayload(oid("1"), HASH, "cat1"),
    ExtractOfferPayload(oid("1"), HASH, "cat1", force=True, request_tag="v3"),
]


class TestDedupKeys:
    def test_keys_follow_adr_0006(self) -> None:
        assert dedup_key(PAYLOADS[0], RUN) == "discover:run1:https://x.test/?page=2"
        assert dedup_key(PAYLOADS[1], RUN) == "enrich:olx_pl:1:run1"
        assert dedup_key(PAYLOADS[2], None) == "enrich:olx_pl:1:refresh:t"
        assert dedup_key(PAYLOADS[3], RUN) == f"extract:olx_pl:1:{HASH}:cat1"
        assert dedup_key(PAYLOADS[4], None) == f"extract:olx_pl:1:{HASH}:cat1:v3"

    def test_scope_is_required(self) -> None:
        with pytest.raises(InvalidValueError):
            dedup_key(PAYLOADS[0], None)
        with pytest.raises(InvalidValueError):
            dedup_key(PAYLOADS[1], None)

    def test_job_type(self) -> None:
        types = [Job.new(JobId("j"), p, run_id=RUN, now=T0).type for p in PAYLOADS[:2]]
        assert types == [JobType.DISCOVER_PAGE, JobType.ENRICH_OFFER]


class TestCodec:
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_payload_round_trip(self, payload: JobPayload) -> None:
        job_type = Job.new(JobId("j"), payload, run_id=RUN, now=T0).type
        assert decode_payload(job_type, encode_payload(payload)) == payload

    def test_result_round_trip(self) -> None:
        metrics = RunMetrics(
            discovery=PhaseMetrics(
                accepted=3,
                rejected=1,
                present={"price": 2},
                applicable={"price": 3},
                outcomes={FetchOutcome.OK: 1, FetchOutcome.BLOCKED: 2},
            ),
            usage=TokenUsage(10, 2, Decimal("0.0012")),
            coverage=DiscoveryCoverage(2, 1000, True),
            failed_jobs=1,
        )
        result = JobResult(metrics, ("note",))
        assert decode_result(encode_result(result)) == result
        assert decode_metrics(encode_metrics(RunMetrics())) == RunMetrics()

    def test_encoded_result_is_json_compatible(self) -> None:
        import json

        json.dumps(encode_result(JobResult(RunMetrics(usage=TokenUsage(1, 1, Decimal("1"))))))


def job(job_id: str, payload: JobPayload, minutes: int = 0) -> Job:
    return Job.new(JobId(job_id), payload, run_id=RUN, now=T0 + timedelta(minutes=minutes))


class TestInMemoryJobQueue:
    async def test_dedup_forever(self) -> None:
        store = InMemoryStore()
        async with store.uow() as uow:
            assert await uow.jobs.enqueue(job("j1", PAYLOADS[1]))
            assert not await uow.jobs.enqueue(job("j2", PAYLOADS[1]))
            await uow.commit()
        async with store.uow() as uow:
            (claimed,) = await uow.jobs.claim([], limit=10, now=T0)
            await uow.jobs.complete(claimed.id, JobResult(), now=T0)
            assert not await uow.jobs.enqueue(job("j3", PAYLOADS[1]))  # also after DONE
            await uow.commit()

    async def test_claim_fifo_due_and_typed(self) -> None:
        store = InMemoryStore()
        async with store.uow() as uow:
            await uow.jobs.enqueue(job("late", PAYLOADS[3], minutes=5))
            await uow.jobs.enqueue(job("first", PAYLOADS[0]))
            await uow.jobs.enqueue(job("second", PAYLOADS[1]))
            await uow.commit()
        async with store.uow() as uow:
            assert [j.id.value for j in await uow.jobs.claim([], limit=10, now=T0)] == [
                "first",
                "second",
            ]
            later = T0 + timedelta(minutes=5)
            assert await uow.jobs.claim([JobType.ENRICH_OFFER], limit=10, now=later) == []
            (late,) = await uow.jobs.claim([JobType.EXTRACT_OFFER], limit=10, now=later)
            assert late.status is JobStatus.RUNNING
            assert late.attempts == 1

    async def test_fail_with_and_without_retry_and_requeue(self) -> None:
        store = InMemoryStore()
        async with store.uow() as uow:
            await uow.jobs.enqueue(job("j", PAYLOADS[1]))
            (claimed,) = await uow.jobs.claim([], limit=1, now=T0)
            retry_at = T0 + timedelta(minutes=1)
            await uow.jobs.fail(claimed.id, error="403", retry_at=retry_at, now=T0)
            retried = await uow.jobs.get(claimed.id)
            assert retried is not None
            assert (retried.status, retried.available_at, retried.attempts) == (
                JobStatus.PENDING,
                retry_at,
                1,
            )
            assert await uow.jobs.count_unfinished(RUN) == 1
            (again,) = await uow.jobs.claim([], limit=1, now=retry_at)
            await uow.jobs.fail(again.id, error="403", retry_at=None, now=retry_at)
            assert await uow.jobs.count_unfinished(RUN) == 0
            assert await uow.jobs.requeue_failed(RUN, now=retry_at) == 1
            requeued = await uow.jobs.get(again.id)
            assert requeued is not None
            assert (requeued.status, requeued.attempts) == (JobStatus.PENDING, 0)

    async def test_requeue_orphaned_resets_running_jobs_keeping_attempts(self) -> None:
        store = InMemoryStore()
        async with store.uow() as uow:
            await uow.jobs.enqueue(job("a", PAYLOADS[0]))
            await uow.jobs.enqueue(job("b", PAYLOADS[1]))
            await uow.jobs.enqueue(job("c", PAYLOADS[2]))
            claimed = await uow.jobs.claim([], limit=2, now=T0)  # a, b
            await uow.jobs.complete(claimed[1].id, JobResult(), now=T0)
            later = T0 + timedelta(hours=1)
            assert await uow.jobs.requeue_orphaned(now=later) == 1
            a = await uow.jobs.get(JobId("a"))
            assert a is not None
            assert (a.status, a.attempts, a.available_at) == (JobStatus.PENDING, 1, later)
            b = await uow.jobs.get(JobId("b"))
            assert b is not None
            assert b.status is JobStatus.DONE
            assert await uow.jobs.requeue_orphaned(now=later) == 0

    async def test_uncommitted_work_is_discarded(self) -> None:
        store = InMemoryStore()
        async with store.uow() as uow:
            await uow.jobs.enqueue(job("j", PAYLOADS[1]))
        async with store.uow() as uow:
            assert await uow.jobs.get(JobId("j")) is None

    async def test_exception_rolls_back(self) -> None:
        store = InMemoryStore()

        async def failing_transaction() -> None:
            async with store.uow() as uow:
                await uow.jobs.enqueue(job("j", PAYLOADS[1]))
                raise RuntimeError

        with pytest.raises(RuntimeError):
            await failing_transaction()
        assert store.state.jobs == {}


class TestRetryPolicy:
    def test_backoff_and_exhaustion(self) -> None:
        policy = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=10))
        assert policy.retry_at(1, T0) == T0 + timedelta(seconds=10)
        assert policy.retry_at(2, T0) == T0 + timedelta(seconds=20)
        assert policy.retry_at(3, T0) is None

    def test_hint_is_honored_when_longer(self) -> None:
        policy = RetryPolicy(base_delay=timedelta(seconds=10))
        assert policy.retry_at(1, T0, timedelta(minutes=5)) == T0 + timedelta(minutes=5)
        assert policy.retry_at(1, T0, timedelta(seconds=1)) == T0 + timedelta(seconds=10)

    def test_capped(self) -> None:
        policy = RetryPolicy(max_attempts=50, max_delay=timedelta(minutes=1))
        assert policy.retry_at(30, T0) == T0 + timedelta(minutes=1)

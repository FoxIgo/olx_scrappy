"""The parallel pool (ADR 0010 section 9): one lane per profile, each within its own limits."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from tests.unit.application.harness import App, classify_by_title
from tests.unit.application.test_extraction import seeded
from tests.unit.fakes import ScriptedExtractor
from tests.unit.fakes.extraction import make_profile, profiles_of


class Timed:
    """Answers after ``delay`` seconds; ``shared`` counts the calls in flight across lanes."""

    def __init__(self, delay: float, shared: list[int] | None = None) -> None:
        self.delay = delay
        self.shared = shared if shared is not None else [0, 0]  # [now, peak]
        self.calls: list[ExtractionInput] = []

    async def extract(self, request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
        self.calls.append(request)
        self.shared[0] += 1
        self.shared[1] = max(self.shared[1], self.shared[0])
        await asyncio.sleep(self.delay)
        self.shared[0] -= 1
        return classify_by_title(request)


def per_minute(seconds: float = 45.0) -> ScriptedExtractor:
    def answer(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection(
            "HTTP 429", retryable=True, kind=RejectionKind.QUOTA, retry_after_seconds=seconds
        )

    return ScriptedExtractor(answer)


async def test_lanes_run_concurrently_and_the_faster_one_takes_more() -> None:
    shared = [0, 0]
    fast, slow = Timed(0.0, shared), Timed(0.05, shared)
    app = App(
        profiles=profiles_of(
            make_profile("fast", fast, concurrency=2),
            make_profile("slow", slow, concurrency=2),
            pool=["fast", "slow"],
        )
    )
    await seeded(app, 16)
    report = await app.reconcile()
    assert report.stored == 16
    assert not report.unavailable
    assert len(fast.calls) > 0
    assert len(slow.calls) > 0  # both lanes made progress
    assert len(fast.calls) > len(slow.calls)  # the faster profile naturally takes more
    assert shared[1] > 2  # calls of both lanes were in flight together (2 per lane at most)
    assert report.stored_by_profile == {"fast": len(fast.calls), "slow": len(slow.calls)}
    ids = [c.offer_id for c in fast.calls + slow.calls]
    assert len(ids) == len(set(ids)) == 16  # leases: no offer was taken by two lanes


async def test_a_blocked_lane_does_not_stop_the_others_and_resumes_when_unblocked() -> None:
    flaky, steady = per_minute(60.0), Timed(0.001)
    app = App(
        profiles=profiles_of(
            make_profile("flaky", flaky), make_profile("steady", steady), pool=["flaky", "steady"]
        )
    )
    await seeded(app, 6)
    report = await app.reconcile()
    assert report.stored == 6
    assert report.stored_by_profile == {"steady": 6}
    assert not report.unavailable  # one lane was blocked, the pool as a whole was not
    assert all(s.attempts == 0 for s in app.store.state.extraction_states.values())

    flaky_calls = len(flaky.calls)
    await seeded(app, 2, start=10)
    await app.reconcile()
    assert len(flaky.calls) == flaky_calls  # still blocked: not asked again

    app.clock.current += timedelta(minutes=2)
    await seeded(app, 2, start=20)
    await app.reconcile()
    assert len(flaky.calls) > flaky_calls  # the lane resumed after its pause


async def test_all_lanes_blocked_reports_unavailable_with_the_short_wait() -> None:
    app = App(
        profiles=profiles_of(
            make_profile("a", per_minute()), make_profile("b", per_minute()), pool=["a", "b"]
        )
    )
    await seeded(app, 3)
    report = await app.reconcile()
    assert report.stored == 0
    assert report.unavailable
    assert report.retry_in is not None
    assert 0 < report.retry_in <= 45.0


async def test_a_daily_limited_lane_stops_at_its_limit() -> None:
    limited, other = Timed(0.001), Timed(0.01)
    app = App(
        profiles=profiles_of(
            make_profile("limited", limited, daily_limit=3),
            make_profile("other", other),
            pool=["limited", "other"],
        )
    )
    await seeded(app, 10)
    report = await app.reconcile()
    assert report.stored == 10
    assert len(limited.calls) == 3
    assert len(other.calls) == 7
    status = await app.extraction_status()
    view = next(v for v in status.profiles if v.profile.name == "limited")
    assert view.blocked
    assert view.quota_status.requests_today == 3


async def test_profiles_of_a_quota_group_share_one_daily_counter() -> None:
    a, b = Timed(0.001), Timed(0.001)
    app = App(
        profiles=profiles_of(
            make_profile("a", a, daily_limit=4, quota_group="free", concurrency=2),
            make_profile("b", b, daily_limit=4, quota_group="free", concurrency=2),
            pool=["a", "b"],
        )
    )
    await seeded(app, 10)
    report = await app.reconcile()
    assert len(a.calls) + len(b.calls) == 4  # the group's limit, not 4 per profile
    assert report.stored == 4
    assert report.unavailable  # both lanes hit the shared limit
    status = await app.extraction_status()
    views = {v.profile.name: v for v in status.profiles}
    assert views["a"].blocked
    assert views["b"].blocked
    assert views["a"].quota_status.requests_today == views["b"].quota_status.requests_today == 4
    assert views["a"].status.requests_today == 0  # counted on the group row only


async def test_a_group_day_block_blocks_every_member() -> None:
    def day(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection(
            "free-models-per-day", retryable=True, kind=RejectionKind.QUOTA, day_exhausted=True
        )

    app = App(
        profiles=profiles_of(
            make_profile("a", ScriptedExtractor(day), quota_group="free"),
            make_profile("b", Timed(0.001), quota_group="free"),
            pool=["a", "b"],
        )
    )
    await seeded(app, 2)
    report = await app.reconcile()
    assert report.unavailable
    status = await app.extraction_status()
    assert all(v.blocked for v in status.profiles)  # b never failed, but shares the group


async def test_the_claim_budget_is_shared_by_all_lanes() -> None:
    a, b = Timed(0.001), Timed(0.001)
    app = App(profiles=profiles_of(make_profile("a", a), make_profile("b", b), pool=["a", "b"]))
    await seeded(app, 10)
    report = await app.reconcile(limit=5)
    assert report.processed == 5
    assert len(a.calls) + len(b.calls) == 5

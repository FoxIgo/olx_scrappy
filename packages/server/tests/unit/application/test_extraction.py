"""The reconciling extractor over fakes (ADR 0010): sync and batch modes, failures,
backoff and parking, bisecting, expiry, crash recovery, leases, profiles and fallback.

Re-run unchanged against SQLite by ``tests/integration/persistence/test_unit_suite_on_sql``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scrappy.application.extraction.batch import BatchStatus
from scrappy.application.extraction.profile_status import ProfileStatus, next_reset, quota_tz
from scrappy.application.policy import ExtractionPolicy, PipelinePolicy
from scrappy.application.ports.extraction_backends import (
    BatchBackendError,
    BatchSettings,
    ExtractionMode,
    StaticExtractionProfiles,
    batch_custom_id,
    parse_custom_id,
)
from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.application.ports.listing_source import SearchPageResult
from scrappy.application.ports.repositories import BacklogQuery
from scrappy.application.use_cases.extraction import ProvenanceFilter, RequestPacer
from scrappy.domain.extraction import ExtractionRetryPolicy
from scrappy.domain.offer import ObservationLevel, OfferId, OfferObservation
from scrappy.domain.run import RunStatus, ScrapeRun
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId, SourceId
from tests.unit.application.harness import App, classify_by_title
from tests.unit.builders import LAPTOP, details, oid
from tests.unit.fakes import FakeClock, ScriptedExtractor
from tests.unit.fakes.extraction import (
    PROMPT,
    FakeBatchBackend,
    FakeHealth,
    make_profile,
    profiles_of,
)

SEARCH = SearchName("laptops")
URL = "https://www.olx.pl/oferty/q-laptop/"
POLICY = PipelinePolicy(
    extraction=ExtractionPolicy(
        retry=ExtractionRetryPolicy(2, timedelta(minutes=1), timedelta(hours=1))
    )
)


async def seeded(app: App, count: int = 3, *, start: int = 1) -> list[OfferId]:
    """``count`` detail-complete laptop offers found by one run (no enrichment needed)."""
    source = app.sources.get(SourceId("olx_pl"))
    if source is None:
        source = app.add_source("olx_pl")
        await app.add_search(SEARCH, SourceId("olx_pl"), URL, LAPTOP)
    observations = tuple(
        details(str(n), title=f"Laptop {n}", description=f"laptop number {n}")
        for n in range(start, start + count)
    )
    source.script_page(URL, SearchPageResult(FetchOutcome.OK, observations=observations))  # type: ignore[attr-defined]
    await app.start_run(SEARCH)
    await app.drain()
    return [o.offer_id for o in observations]


def batch_app(backend_script: bool = True, **profile: object) -> tuple[App, FakeBatchBackend]:
    clock = FakeClock()
    backend = FakeBatchBackend(clock, classify_by_title if backend_script else None)
    extractor = ScriptedExtractor(classify_by_title)
    options: dict[str, object] = {"mode": ExtractionMode.BATCH, "backend": backend}
    options.update(profile)
    app = App(
        clock=clock,
        policy=POLICY,
        extractor=extractor,
        profiles=profiles_of(make_profile("remote", extractor, **options)),  # type: ignore[arg-type]
    )
    return app, backend


async def change_content(app: App, offer_id: OfferId) -> None:
    async with app.store.uow() as uow:
        offer = await uow.offers.get(offer_id)
        assert offer is not None
        offer.apply(
            OfferObservation(offer_id, ObservationLevel.DETAILS, description="edited text"),
            app.clock.now(),
        )
        await uow.offers.save(offer)
        await uow.commit()


# ---------------------------------------------------------------------------- sync mode


class SlowExtractor:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls: list[ExtractionInput] = []

    async def extract(self, request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.005)
        self.in_flight -= 1
        return classify_by_title(request)


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_sync_mode_respects_the_profile_concurrency(concurrency: int) -> None:
    slow = SlowExtractor()
    app = App(profiles=profiles_of(make_profile("local", slow, concurrency=concurrency)))
    await seeded(app, 6)
    assert await app.extract() == 6
    assert len(slow.calls) == 6
    assert slow.max_in_flight == concurrency


async def test_request_pacer_spaces_call_starts() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    pacer = RequestPacer(30, monotonic=lambda: 100.0, sleep=fake_sleep)  # every 2 s
    for _ in range(3):
        await pacer.wait()
    assert sleeps == [2.0, 4.0]
    unlimited = RequestPacer(None, sleep=fake_sleep)
    await unlimited.wait()
    assert sleeps == [2.0, 4.0]


async def test_sync_results_carry_profile_provenance_and_relevance() -> None:
    app = App()
    ids = await seeded(app, 2)
    report = await app.reconcile()
    assert (report.profile, report.mode, report.stored) == ("main", "sync", 2)
    state = app.store.state
    extraction = state.extractions[0]
    assert extraction.provenance.profile == "main"
    assert extraction.provenance.provider == "fake-main"
    assert extraction.provenance.prompt_version == PROMPT
    assert not extraction.provenance.cost_estimated
    assert state.links[(SEARCH, ids[0])].is_relevant is True
    assert all(s.lease_owner is None for s in state.extraction_states.values())


async def test_limit_caps_the_offers_claimed_in_sync_mode() -> None:
    app = App()
    await seeded(app, 5)
    report = await app.reconcile(limit=3)
    assert report.stored == 3
    assert (await app.reconcile(limit=3)).stored == 2


async def test_limit_caps_the_offers_claimed_in_a_batch() -> None:
    app, backend = batch_app()
    await seeded(app, 5)
    report = await app.reconcile(flush=True, limit=2)
    assert report.batches_submitted == 1
    assert [len(b.items) for b in backend.batches.values()] == [2]


# ---------------------------------------------------------------------------- batch mode


async def test_batch_happy_path_with_estimated_cost() -> None:
    app, backend = batch_app()
    ids = await seeded(app, 3)

    report = await app.reconcile()
    assert (report.mode, report.batches_submitted) == ("batch", 1)
    (batch,) = app.store.state.batches.values()
    assert batch.status is BatchStatus.SUBMITTED
    assert batch.provider_batch_id == "pb1"
    assert {item.offer_id for item in batch.items} == set(ids)
    assert batch.items[0].custom_id == batch_custom_id(
        batch.items[0].offer_id, batch.items[0].content_hash
    )
    assert all(
        s.lease_owner == f"batch:{batch.id}" for s in app.store.state.extraction_states.values()
    )
    assert await app.backlog() == 0  # leased
    status = await app.extraction_status()
    assert [b.id for b in status.open_batches] == [batch.id]

    assert (await app.poll()).running == 1
    backend.complete("pb1", cost="0.003")
    polled = await app.poll()
    assert (polled.completed, polled.stored) == (1, 3)
    state = app.store.state
    done = state.batches[batch.id]
    assert done.status is BatchStatus.COMPLETED
    assert done.succeeded == 3
    assert done.usage.cost_usd == Decimal("0.003")
    assert all(e.provenance.batch_id == batch.id for e in state.extractions)
    assert all(e.provenance.cost_estimated for e in state.extractions)
    total = sum((e.usage.cost_usd or Decimal(0)) for e in state.extractions)
    assert total == Decimal("0.003")
    assert all(s.lease_owner is None for s in state.extraction_states.values())
    assert await app.backlog() == 0


async def test_batch_mode_waits_for_min_size_unless_flushed() -> None:
    app, backend = batch_app()
    await seeded(app, 2)
    report = await app.reconcile()
    assert report.batches_submitted == 0
    assert any("wait for a batch" in n for n in report.notes)
    assert (await app.reconcile(flush=True)).batches_submitted == 1
    assert len(backend.batches) == 1


@pytest.mark.parametrize(("offers", "mode"), [(2, "sync"), (3, "batch")])
async def test_auto_mode_uses_batch_from_min_size(offers: int, mode: str) -> None:
    app, _ = batch_app(mode=ExtractionMode.AUTO)
    await seeded(app, offers)
    assert (await app.reconcile()).mode == mode


async def test_stale_results_are_discarded_and_the_offer_stays_in_the_backlog() -> None:
    app, backend = batch_app()
    ids = await seeded(app, 3)
    await app.reconcile()
    await change_content(app, ids[0])  # edited while the batch runs
    backend.complete("pb1")
    polled = await app.poll()
    assert (polled.stored, polled.stale) == (2, 1)
    assert {e.offer_id for e in app.store.state.extractions} == set(ids[1:])
    assert await app.backlog() == 1  # back by the content-hash rule, not via the batch


async def test_item_failures_back_off_then_park_and_a_manual_retry_unparks() -> None:
    app, backend = batch_app()
    ids = await seeded(app, 3)
    bad = ExtractionRejection("refusal", retryable=False, kind=RejectionKind.PERMANENT)
    await app.reconcile()
    backend.complete("pb1", {batch_custom_id(ids[0], _hash(app, ids[0])): bad})
    polled = await app.poll()
    assert (polled.stored, polled.item_failures) == (2, 1)
    state = app.store.state.extraction_states[ids[0]]
    assert state.attempts == 1
    assert state.next_attempt_at is not None
    assert not state.parked
    assert await app.backlog() == 0  # in backoff

    app.clock.advance(timedelta(minutes=2))
    assert await app.backlog() == 1
    await app.reconcile(flush=True)
    backend.complete("pb2", {batch_custom_id(ids[0], _hash(app, ids[0])): bad})
    await app.poll()
    assert app.store.state.extraction_states[ids[0]].parked
    app.clock.advance(timedelta(days=1))
    assert await app.backlog() == 0
    status = await app.extraction_status()
    assert [s.offer_id for s in status.parked] == [ids[0]]

    retried = await app.force_reextract(parked_only=True)
    assert retried.marked == 1
    assert await app.backlog() == 1


async def test_a_failed_batch_is_bisected_until_the_bad_item_is_found() -> None:
    app, backend = batch_app()
    ids = await seeded(app, 4)
    poison = ids[1]
    backend.fail_submit_when = lambda items: (
        "invalid request" if any(i.input.offer_id == poison for i in items) else None
    )
    backend.auto = True
    await app.extract()

    state = app.store.state
    assert {e.offer_id for e in state.extractions} == set(ids) - {poison}
    culprit = state.extraction_states[poison]
    assert culprit.attempts == 1
    assert culprit.last_error is not None
    assert "invalid request" in culprit.last_error
    failed = [b for b in state.batches.values() if b.status is BatchStatus.FAILED]
    assert [len(b.items) for b in failed] == [4, 2, 1]
    assert all(b.parent_id is not None for b in failed[1:])
    for other in set(ids) - {poison}:
        assert state.extraction_states[other].attempts == 0  # no penalty for the innocent


async def test_an_expired_batch_releases_its_offers_without_penalty() -> None:
    app, backend = batch_app()
    await seeded(app, 3)
    await app.reconcile()
    backend.expire("pb1")
    assert (await app.poll()).expired == 1
    states = app.store.state.extraction_states.values()
    assert all(s.lease_owner is None and s.attempts == 0 for s in states)
    assert await app.backlog() == 3
    assert (await app.reconcile()).batches_submitted == 1  # resubmitted


async def test_a_submitting_row_left_by_a_crash_is_recovered_or_requeued() -> None:
    app, backend = batch_app()
    await seeded(app, 3)
    await app.reconcile()
    (batch_id,) = app.store.state.batches

    async def crash_after_post() -> None:
        """The POST went out but ``mark_submitted`` never committed."""
        async with app.store.uow() as uow:
            batch = await uow.extraction_batches.get(batch_id)
            assert batch is not None
            batch.status = BatchStatus.SUBMITTING
            batch.provider_batch_id = None
            batch.submitted_at = None
            batch.submitting_at = app.clock.now()
            await uow.extraction_batches.save(batch)
            await uow.commit()

    await crash_after_post()
    assert (await app.poll()).recovered == 0  # not yet: it may still be in flight
    recovered = await app.poll(recover=True)  # extractor start
    assert recovered.recovered == 1
    batch = app.store.state.batches[batch_id]
    assert (batch.status, batch.provider_batch_id) == (BatchStatus.SUBMITTED, "pb1")

    await crash_after_post()
    backend.batches.clear()  # the provider never got it
    app.clock.advance(timedelta(minutes=11))  # past submitting_timeout
    assert (await app.poll()).recovered == 1
    assert app.store.state.batches[batch_id].status is BatchStatus.QUEUED
    report = await app.reconcile()
    assert report.batches_submitted == 1
    assert app.store.state.batches[batch_id].status is BatchStatus.SUBMITTED


@pytest.mark.parametrize(
    ("kind", "blocked"),
    [(RejectionKind.QUOTA, True), (RejectionKind.TRANSIENT, False)],
)
async def test_submit_errors_release_without_penalty(kind: RejectionKind, blocked: bool) -> None:
    app, backend = batch_app()
    await seeded(app, 3)
    backend.submit_error = BatchBackendError("HTTP 402 insufficient credits", kind=kind)
    report = await app.reconcile()
    assert report.batches_submitted == 0
    (batch,) = app.store.state.batches.values()
    assert batch.status is BatchStatus.FAILED
    assert all(
        s.lease_owner is None and s.attempts == 0
        for s in app.store.state.extraction_states.values()
    )
    assert await app.backlog() == 3
    status = await app.extraction_status()
    assert status.profiles[0].blocked is blocked
    assert report.unavailable is blocked


async def test_abandon_is_a_local_cancel() -> None:
    app, backend = batch_app()
    await seeded(app, 3)
    await app.reconcile()
    (batch_id,) = app.store.state.batches
    assert await app.reconcile.abandon(batch_id, "user cancelled")
    assert not await app.reconcile.abandon(batch_id, "again")
    assert app.store.state.batches[batch_id].status is BatchStatus.ABANDONED
    backend.complete("pb1")
    assert (await app.poll()).polled == 0  # results of an abandoned batch are ignored
    assert app.store.state.extractions == []
    assert await app.backlog() == 3


# ---------------------------------------------------------------------------- leases


async def test_leases_are_exclusive_and_expire() -> None:
    app = App()
    ids = await seeded(app, 2)
    now = app.clock.now()
    query = BacklogQuery(app.catalog, PROMPT, now)
    async with app.store.uow() as uow:
        first = await uow.extraction_states.claim(
            query, owner="sync:a", lease_until=now + timedelta(minutes=10), limit=1
        )
        await uow.commit()
    async with app.store.uow() as uow:
        second = await uow.extraction_states.claim(
            query, owner="sync:b", lease_until=now + timedelta(minutes=10), limit=5
        )
        await uow.commit()
    assert len(first) == 1
    assert len(second) == 1
    assert set(first + second) == set(ids)
    assert await app.backlog() == 0

    app.clock.advance(timedelta(minutes=11))  # the owners died: leases expire
    assert await app.backlog() == 2
    later = BacklogQuery(app.catalog, PROMPT, app.clock.now())
    async with app.store.uow() as uow:
        retaken = await uow.extraction_states.claim(
            later, owner="sync:c", lease_until=app.clock.now() + timedelta(minutes=1), limit=5
        )
        assert await uow.extraction_states.release_owner("sync:c", now=app.clock.now()) == 2
        await uow.commit()
    assert retaken == [ids[0], ids[1]] or set(retaken) == set(ids)


async def test_backlog_is_scoped_by_search() -> None:
    app = App()
    await seeded(app, 2)
    async with app.store.uow() as uow:
        query = BacklogQuery(app.catalog, PROMPT, app.clock.now(), search=SearchName("none"))
        assert await uow.extraction_states.count_backlog(query) == 0
    assert await app.extraction_status.backlog(SEARCH) == 2


# ---------------------------------------------------------------------------- profiles


async def test_fallback_to_the_next_profile_when_health_fails() -> None:
    local = ScriptedExtractor(classify_by_title)
    remote = ScriptedExtractor(classify_by_title)
    profiles = profiles_of(
        make_profile("local", local, health=FakeHealth(False, "cannot reach localhost:11434")),
        make_profile("remote", remote),
        fallback=["remote"],
    )
    app = App(profiles=profiles)
    await seeded(app, 2)
    report = await app.reconcile()
    assert report.profile == "remote"
    assert any("localhost:11434" in n for n in report.notes)
    assert local.calls == []
    assert {e.provenance.profile for e in app.store.state.extractions} == {"remote"}


async def test_402_blocks_the_profile_without_penalty_and_falls_back() -> None:
    def broke(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection("HTTP 402: no credits", retryable=True, kind=RejectionKind.QUOTA)

    cheap = ScriptedExtractor(broke)
    backup = ScriptedExtractor(classify_by_title)
    app = App(
        profiles=profiles_of(
            make_profile("cheap", cheap), make_profile("backup", backup), fallback=["backup"]
        )
    )
    await seeded(app, 3)
    report = await app.reconcile()
    assert report.stored == 3
    assert {e.provenance.profile for e in app.store.state.extractions} == {"backup"}
    assert all(s.attempts == 0 for s in app.store.state.extraction_states.values())
    status = await app.extraction_status()
    cheap_view = next(v for v in status.profiles if v.profile.name == "cheap")
    assert cheap_view.blocked
    assert "402" in (cheap_view.status.reason or "")

    calls = len(cheap.calls)
    await seeded(app, 1, start=10)
    await app.reconcile()
    assert len(cheap.calls) == calls  # still blocked: not asked again


async def test_no_available_profile_parks_nothing_and_reports_it() -> None:
    def unavailable(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection(
            "connection refused", retryable=True, kind=RejectionKind.UNAVAILABLE
        )

    app = App(profiles=profiles_of(make_profile("local", ScriptedExtractor(unavailable))))
    await seeded(app, 2)
    report = await app.reconcile()
    assert report.unavailable
    assert report.stored == 0
    assert all(s.attempts == 0 for s in app.store.state.extraction_states.values())
    assert await app.backlog() == 2
    again = await app.reconcile()  # marked unhealthy: not even tried until the TTL passes
    assert again.unavailable
    assert again.processed == 0


async def test_daily_limit_makes_the_profile_unavailable_until_tomorrow() -> None:
    app = App(
        profiles=profiles_of(
            make_profile("free", ScriptedExtractor(classify_by_title), daily_limit=2)
        )
    )
    await seeded(app, 3)
    report = await app.reconcile()
    assert report.stored == 2
    assert report.unavailable
    status = await app.extraction_status()
    assert status.profiles[0].blocked
    assert status.profiles[0].status.requests_on(app.clock.now()) == 2
    app.clock.advance(timedelta(days=1))
    assert (await app.reconcile()).stored == 1


async def test_forced_work_pinned_to_a_profile_is_done_by_that_profile() -> None:
    main = ScriptedExtractor(classify_by_title)
    better = ScriptedExtractor(classify_by_title)
    app = App(profiles=profiles_of(make_profile("main", main), make_profile("better", better)))
    ids = await seeded(app, 2)
    await app.extract()
    result = await app.force_reextract(
        where=[ProvenanceFilter("profile", "=", "main")], profile="better"
    )
    assert result.marked == 2
    await app.extract()
    assert len(main.calls) == 2
    assert len(better.calls) == 2
    latest = {
        e.offer_id: e.provenance.profile
        for e in sorted(app.store.state.extractions, key=lambda e: e.provenance.extracted_at)
    }
    assert latest == {ids[0]: "better", ids[1]: "better"}
    with pytest.raises(Exception, match="unknown profile"):
        await app.force_reextract(profile="nope")


async def test_provenance_filters() -> None:
    app = App()
    await seeded(app, 1)
    await app.extract()
    extraction = app.store.state.extractions[0]
    assert ProvenanceFilter("model", "~", "FAKE").matches(extraction)
    assert ProvenanceFilter("provider", "!=", "x").matches(extraction)
    assert not ProvenanceFilter("category", "=", "other").matches(extraction)
    with pytest.raises(Exception, match="unknown field"):
        ProvenanceFilter("colour", "=", "red")


# ---------------------------------------------------------------------------- misc


async def test_finalize_idle_runs_closes_runs_without_work() -> None:
    app = App()
    await seeded(app, 1)
    run = ScrapeRun(RunId("legacy"), SEARCH, SourceId("olx_pl"), app.clock.now())
    async with app.store.uow() as uow:
        await uow.runs.save(run)
        await uow.commit()
    finished = await app.finalize_idle_runs()
    assert [r.id for r in finished] == [RunId("legacy")]
    assert app.store.state.runs[RunId("legacy")].status is not RunStatus.RUNNING


def test_port_value_objects() -> None:
    offer_id = oid("1098526767")
    content_hash = _any_hash()
    custom_id = batch_custom_id(offer_id, content_hash)
    assert custom_id == f"olx_pl:1098526767@{content_hash}"
    assert parse_custom_id(custom_id) == (offer_id, content_hash)
    with pytest.raises(InvalidValueError):
        parse_custom_id("no-at-sign")
    assert ExtractionRejection("x", retryable=True).rejection_kind is RejectionKind.TRANSIENT
    assert ExtractionRejection("x", retryable=False).rejection_kind is RejectionKind.INVALID_OUTPUT
    assert not RejectionKind.QUOTA.penalizes_offer
    extractor = ScriptedExtractor(classify_by_title)
    with pytest.raises(InvalidValueError):
        StaticExtractionProfiles({"a": make_profile("a", extractor)}, default_profile="b")
    with pytest.raises(InvalidValueError):
        BatchSettings(min_size=5, max_size=2)
    profile = make_profile("a", extractor, mode=ExtractionMode.BATCH)
    assert not profile.wants_batch(100)  # no backend: always sync


def _any_hash():  # type: ignore[no-untyped-def]
    from scrappy.domain.offer import ContentHash

    return ContentHash("ab" * 32)


def _hash(app: App, offer_id: OfferId):  # type: ignore[no-untyped-def]
    content_hash = app.store.state.offers[offer_id].content_hash
    assert content_hash is not None
    return content_hash


# ---------------------------------------------------------------- quota day / Pacific reset
LA = "America/Los_Angeles"


async def test_daily_limit_resets_at_midnight_in_the_profile_timezone() -> None:
    app = App(
        profiles=profiles_of(
            make_profile(
                "g", ScriptedExtractor(classify_by_title), daily_limit=2, quota_timezone=LA
            )
        )
    )
    app.clock.current = datetime(2026, 10, 2, 6, 40, tzinfo=UTC)  # 23:40 Pacific (PDT)
    await seeded(app, 3)
    assert (await app.reconcile()).stored == 2
    app.clock.current = datetime(2026, 10, 2, 6, 59, tzinfo=UTC)  # 23:59 Pacific: same day
    assert (await app.reconcile()).stored == 0
    app.clock.current = datetime(2026, 10, 2, 7, 1, tzinfo=UTC)  # 00:01 Pacific: new day
    assert (await app.reconcile()).stored == 1


def test_next_reset_follows_the_timezone_including_dst() -> None:
    pacific = quota_tz(LA)
    summer = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    assert next_reset(summer, pacific) == datetime(2026, 10, 2, 7, 0, tzinfo=UTC)  # PDT
    winter = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    assert next_reset(winter, pacific) == datetime(2026, 12, 2, 8, 0, tzinfo=UTC)  # PST
    assert next_reset(summer) == datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
    status = ProfileStatus.new("g", summer)
    status.count_requests(5, summer, pacific)
    assert status.requests_on(datetime(2026, 10, 2, 6, 59, tzinfo=UTC), pacific) == 5
    assert status.requests_on(datetime(2026, 10, 2, 7, 0, tzinfo=UTC), pacific) == 0
    with pytest.raises(InvalidValueError):
        quota_tz("Mars/Olympus")


def quota_rejection(**kwargs: object) -> ScriptedExtractor:
    def script(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection(
            "HTTP 429: RESOURCE_EXHAUSTED",
            retryable=True,
            kind=RejectionKind.QUOTA,
            **kwargs,  # type: ignore[arg-type]
        )

    return ScriptedExtractor(script)


async def test_per_day_quota_blocks_until_the_next_reset_and_falls_through_to_the_next() -> None:
    first = quota_rejection(day_exhausted=True)
    second = ScriptedExtractor(classify_by_title)
    app = App(
        profiles=profiles_of(
            make_profile("lite", first, quota_timezone=LA),
            make_profile("gemma", second, quota_timezone=LA),
            fallback=["lite", "gemma"],
        )
    )
    await seeded(app, 3)
    report = await app.reconcile()
    assert report.stored == 3
    assert {e.provenance.profile for e in app.store.state.extractions} == {"gemma"}
    assert all(s.attempts == 0 for s in app.store.state.extraction_states.values())  # no penalty
    status = await app.extraction_status()
    lite = next(v for v in status.profiles if v.profile.name == "lite")
    assert lite.blocked
    assert lite.status.blocked_until == datetime(2026, 10, 2, 7, 0, tzinfo=UTC)
    assert "RESOURCE_EXHAUSTED" in (lite.status.reason or "")
    calls = len(first.calls)
    await seeded(app, 1, start=10)
    await app.reconcile()
    assert len(first.calls) == calls  # not asked again before the reset
    app.clock.current = datetime(2026, 10, 2, 7, 1, tzinfo=UTC)
    await seeded(app, 1, start=20)
    await app.reconcile()
    assert len(first.calls) > calls  # tried again after the Pacific midnight


async def test_per_minute_quota_pauses_the_profile_only_for_the_retry_delay() -> None:
    first = quota_rejection(retry_after_seconds=45.0)
    second = ScriptedExtractor(classify_by_title)
    app = App(
        profiles=profiles_of(
            make_profile("lite", first), make_profile("gemma", second), fallback=["lite", "gemma"]
        )
    )
    await seeded(app, 2)
    assert (await app.reconcile()).stored == 2
    status = await app.extraction_status()
    lite = next(v for v in status.profiles if v.profile.name == "lite")
    assert lite.status.blocked_until == app.clock.now() + timedelta(seconds=45)
    assert all(s.attempts == 0 for s in app.store.state.extraction_states.values())

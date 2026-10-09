"""Failure paths: rejections, missing fields, BLOCKED/TRANSIENT retries, GONE/NOT_FOUND."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from scrappy.application.jobs.model import JobStatus, JobType
from scrappy.application.policy import PipelinePolicy, RetryPolicy
from scrappy.application.ports.extractor import ExtractionInput, ExtractionRejection
from scrappy.application.ports.listing_source import (
    OfferDetailsResult,
    RecordRejection,
    SearchPageResult,
)
from scrappy.domain.offer import OfferStatus, Price, TrackedField
from scrappy.domain.run import RunStatus
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, SourceId
from tests.unit.application.harness import App
from tests.unit.builders import LAPTOP, details, listing, oid
from tests.unit.fakes import ScriptedListingSource

SEARCH = SearchName("gtx-laptops")
URL = "https://www.olx.pl/oferty/q-gtx/"
A = oid("A")


def ok_page(
    *observations: object, rejections: tuple[RecordRejection, ...] = ()
) -> SearchPageResult:
    return SearchPageResult(FetchOutcome.OK, observations=observations, rejections=rejections)  # type: ignore[arg-type]


async def make_app(policy: PipelinePolicy | None = None) -> tuple[App, ScriptedListingSource]:
    app = App(policy=policy or PipelinePolicy())
    source = app.add_source("olx_pl")
    await app.add_search(SEARCH, SourceId("olx_pl"), URL, LAPTOP)
    return app, source


async def test_rejected_records_and_missing_fields_do_not_produce_snapshots() -> None:
    app, source = await make_app()
    source.script_page(
        URL,
        ok_page(listing("A")),
        ok_page(
            replace(listing("A"), price=None, title=None),  # parser lost price and title
            rejections=(RecordRejection("missing price", "B", "raw/page1.html"),),
        ),
    )
    source.script_details(A, OfferDetailsResult.ok(details("A")))
    await app.start_run(SEARCH)
    await app.drain()

    app.clock.advance()
    second = await app.start_run(SEARCH)
    await app.drain()
    state = app.store.state

    assert state.snapshots == []
    assert state.offers[A].price == Price.fixed(1000)
    assert set(state.offers) == {A}  # the rejected record never reached the domain
    assert len(source.detail_calls) == 1  # missing list data is not "changed"
    run = state.runs[second.run.id]
    assert run.metrics.discovery.rejected == 1
    assert run.metrics.discovery.fill_rate("price") == 0.0
    discover_job = app.jobs(JobType.DISCOVER_PAGE)[-1]
    assert discover_job.result is not None
    assert any("raw/page1.html" in note for note in discover_job.result.notes)


async def test_detail_parse_rejection_is_counted_not_retried() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(A, OfferDetailsResult.rejected(RecordRejection("no description", "A")))
    run = await app.start_run(SEARCH)
    await app.drain()
    state = app.store.state

    (enrich,) = app.jobs(JobType.ENRICH_OFFER)
    assert enrich.status is JobStatus.DONE
    assert enrich.attempts == 1
    assert not state.offers[A].has_details  # will be retried by the next run (R8)
    assert app.jobs(JobType.EXTRACT_OFFER) == []
    assert state.runs[run.run.id].metrics.enrichment.rejected == 1


async def test_blocked_fetch_is_retried_later_then_succeeds() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(
        A,
        OfferDetailsResult.failed(FetchOutcome.BLOCKED, "403", retry_after=timedelta(minutes=10)),
        OfferDetailsResult.ok(details("A")),
    )
    started = await app.start_run(SEARCH)
    await app.drain()

    (enrich,) = app.jobs(JobType.ENRICH_OFFER)
    assert enrich.status is JobStatus.PENDING
    assert enrich.attempts == 1
    assert enrich.last_error is not None
    assert "blocked" in enrich.last_error
    assert enrich.available_at >= app.clock.now() + timedelta(minutes=9)
    assert app.store.state.runs[started.run.id].is_running  # unfinished work remains

    app.clock.advance(timedelta(minutes=11))
    await app.drain()
    (enrich,) = app.jobs(JobType.ENRICH_OFFER)
    assert enrich.status is JobStatus.DONE
    assert enrich.attempts == 2
    run = app.store.state.runs[started.run.id]
    assert run.status is RunStatus.COMPLETED
    assert run.metrics.enrichment.outcome_count(FetchOutcome.OK) == 1


async def test_exhausted_retries_make_the_run_partial_and_resume_finishes_it() -> None:
    policy = PipelinePolicy(retry=RetryPolicy(max_attempts=2, base_delay=timedelta(seconds=10)))
    app, source = await make_app(policy)
    source.script_page(URL, ok_page(listing("A")))
    blocked = OfferDetailsResult.failed(FetchOutcome.TRANSIENT, "timeout")
    source.script_details(A, blocked, blocked, OfferDetailsResult.ok(details("A")))
    started = await app.start_run(SEARCH)
    await app.drain()
    app.clock.advance(timedelta(minutes=1))
    await app.drain()

    (enrich,) = app.jobs(JobType.ENRICH_OFFER)
    assert enrich.status is JobStatus.FAILED
    run = app.store.state.runs[started.run.id]
    assert run.status is RunStatus.PARTIAL
    assert run.metrics.failed_jobs == 1
    assert run.metrics.enrichment.outcome_count(FetchOutcome.TRANSIENT) == 1
    assert "timeout" in run.errors[0]

    resumed = await app.resume_run(started.run.id)
    assert resumed.requeued == 1
    assert resumed.run.is_running
    await app.drain()
    run = app.store.state.runs[started.run.id]
    assert run.status is RunStatus.COMPLETED
    assert len(app.jobs(JobType.DISCOVER_PAGE)) == 1  # done pages were not repeated
    assert app.store.state.offers[A].has_details


async def test_failed_first_page_fails_the_run() -> None:
    policy = PipelinePolicy(retry=RetryPolicy(max_attempts=1))
    app, source = await make_app(policy)
    source.script_page(URL, SearchPageResult.failed(FetchOutcome.BLOCKED, "captcha"))
    started = await app.start_run(SEARCH)
    await app.drain()
    run = app.store.state.runs[started.run.id]
    assert run.status is RunStatus.FAILED


async def test_gone_outcome_updates_status_with_snapshot() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(
        A, OfferDetailsResult.ok(details("A")), OfferDetailsResult.gone(OfferStatus.SOLD)
    )
    await app.start_run(SEARCH)
    await app.drain()

    assert await app.refresh_offer(A, "t1")
    assert not await app.refresh_offer(A, "t1")  # same tag: deduplicated
    await app.drain()
    state = app.store.state
    assert state.offers[A].status is OfferStatus.SOLD
    (snapshot,) = state.snapshots
    assert snapshot.changes[0].field is TrackedField.STATUS
    assert snapshot.changes[0].new is OfferStatus.SOLD
    assert snapshot.run_id is None


async def test_not_found_for_known_offer_means_removed() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(A, OfferDetailsResult.ok(details("A")), OfferDetailsResult.not_found())
    await app.start_run(SEARCH)
    await app.drain()
    await app.refresh_offer(A, "t1")
    await app.drain()
    assert app.store.state.offers[A].status is OfferStatus.REMOVED


async def test_not_found_for_unknown_id_stores_nothing() -> None:
    app, _ = await make_app()
    await app.refresh_offer(oid("never-seen"), "t1")
    await app.drain()
    assert app.store.state.offers == {}
    (job,) = app.jobs()
    assert job.status is JobStatus.DONE


async def test_refresh_of_unknown_id_with_details_creates_the_offer() -> None:
    app, source = await make_app()
    source.script_details(oid("N"), OfferDetailsResult.ok(details("N")))
    await app.refresh_offer(oid("N"), "t1")
    await app.drain()
    assert app.store.state.offers[oid("N")].status is OfferStatus.ACTIVE
    assert len(app.jobs(JobType.EXTRACT_OFFER)) == 1


async def test_rejected_llm_output_leaves_offer_pending() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(A, OfferDetailsResult.ok(details("A")))

    def invalid(_: ExtractionInput) -> ExtractionRejection:
        return ExtractionRejection("schema mismatch", retryable=False)

    app.extractor.script = invalid
    started = await app.start_run(SEARCH)
    await app.drain()
    state = app.store.state
    assert state.extractions == []
    assert state.links[(SEARCH, A)].is_relevant is None  # still unknown
    run = state.runs[started.run.id]
    assert run.metrics.extraction.rejected == 1
    assert run.status is RunStatus.COMPLETED  # an LLM failure does not fail the scrape


async def test_invalid_attributes_from_llm_are_rejected_by_the_domain() -> None:
    from scrappy.application.ports.extractor import ExtractionResult

    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(A, OfferDetailsResult.ok(details("A")))
    app.extractor.script = lambda _: ExtractionResult(LAPTOP, {"ram_gb": "lots"}, "m", "p")
    await app.start_run(SEARCH)
    await app.drain()
    assert app.store.state.extractions == []
    (job,) = app.jobs(JobType.EXTRACT_OFFER)
    assert job.result is not None
    assert "invalid extraction" in job.result.notes[0]


async def test_retryable_llm_failure_is_retried() -> None:
    from tests.unit.application.harness import classify_by_title

    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))
    source.script_details(A, OfferDetailsResult.ok(details("A")))
    calls = 0

    def flaky(request: ExtractionInput):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return (
            ExtractionRejection("429", retryable=True) if calls == 1 else classify_by_title(request)
        )

    app.extractor.script = flaky
    await app.start_run(SEARCH)
    await app.drain()
    app.clock.advance(timedelta(minutes=5))
    await app.drain()
    assert len(app.store.state.extractions) == 1


async def test_handler_crash_is_treated_as_retryable() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(listing("A")))

    async def boom(_: object) -> OfferDetailsResult:
        raise RuntimeError("parser bug")

    source.fetch_offer_details = boom  # type: ignore[method-assign]
    await app.start_run(SEARCH)
    await app.drain()
    (enrich,) = app.jobs(JobType.ENRICH_OFFER)
    assert enrich.status is JobStatus.PENDING
    assert enrich.last_error == "RuntimeError: parser bug"


async def test_offer_url_from_source_is_used_for_details() -> None:
    app, source = await make_app()
    source.script_page(URL, ok_page(replace(listing("A"), url="https://x.test/a")))
    source.script_details(A, OfferDetailsResult.ok(details("A")))
    await app.start_run(SEARCH)
    await app.drain()
    assert source.detail_calls[0].url == "https://x.test/a"


async def test_identical_job_errors_are_grouped_in_the_run_report() -> None:
    policy = PipelinePolicy(retry=RetryPolicy(max_attempts=1, base_delay=timedelta(seconds=10)))
    app, source = await make_app(policy)
    source.script_page(URL, ok_page(listing("A"), listing("B"), listing("C")))

    async def boom(_: object) -> OfferDetailsResult:
        raise RuntimeError("parser bug")

    source.fetch_offer_details = boom  # type: ignore[method-assign]
    started = await app.start_run(SEARCH)
    await app.drain()

    run = app.store.state.runs[started.run.id]
    assert run.metrics.failed_jobs == 3
    (error,) = run.errors
    assert error.startswith("enrich_offer x3 (e.g. ")
    assert error.endswith(": RuntimeError: parser bug")

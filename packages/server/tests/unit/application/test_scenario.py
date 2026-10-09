"""End-to-end application scenarios over in-memory fakes (ADR 0006 + ADR 0010 flow):
runs scrape only, the extractor reconciles the backlog afterwards."""

from __future__ import annotations

from scrappy.application.jobs.model import JobStatus, JobType
from scrappy.application.ports.listing_source import (
    OfferDetailsResult,
    PageRef,
    SearchPageResult,
)
from scrappy.application.ports.queries import OfferFilter, RelevanceFilter
from scrappy.domain.offer import Price, TrackedField
from scrappy.domain.run import RunStatus
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, SourceId
from tests.unit.application.harness import App
from tests.unit.builders import LAPTOP, details, listing, oid
from tests.unit.fakes import ScriptedListingSource

SEARCH = SearchName("gtx-laptops")
URL = "https://www.olx.pl/oferty/q-gtx/"
OLX = SourceId("olx_pl")

A, B, C = oid("A"), oid("B"), oid("C")
TITLES = {"A": "Laptop Dell GTX 1650", "B": "Laptop HP GTX 1650", "C": "Zasilacz 120W"}


def page1(b_price: int = 1000) -> SearchPageResult:
    return SearchPageResult(
        FetchOutcome.OK,
        observations=(
            listing("A", title=TITLES["A"], promoted=True),
            listing("B", title=TITLES["B"], price=Price.fixed(b_price)),
            listing("A", title=TITLES["A"], promoted=True),  # promoted repeat on the same page
        ),
        next_page=PageRef("p2", 2),
        total_results=3,
    )


def page2(b_price: int = 1000) -> SearchPageResult:
    return SearchPageResult(
        FetchOutcome.OK,
        observations=(
            listing("C", title=TITLES["C"]),
            listing("B", title=TITLES["B"], price=Price.fixed(b_price)),  # across pages
            listing("A", title=TITLES["A"], promoted=True),
        ),
        total_results=3,
    )


def detail(key: str, price: int = 1000) -> OfferDetailsResult:
    return OfferDetailsResult.ok(details(key, title=TITLES[key], price=Price.fixed(price)))


async def setup_enrichment_search(app: App) -> ScriptedListingSource:
    source = app.add_source("olx_pl")
    source.script_page(URL, page1(), page1(b_price=900))
    source.script_page("p2", page2(), page2(b_price=900))
    source.script_details(A, detail("A"))
    source.script_details(B, detail("B"), detail("B", price=900))
    source.script_details(C, detail("C"))
    await app.add_search(SEARCH, OLX, URL, LAPTOP)
    return source


async def test_two_runs_with_enrichment_source() -> None:
    app = App()
    source = await setup_enrichment_search(app)

    # ------------------------------------------------------------------ run 1
    first = await app.start_run(SEARCH)
    await app.drain()
    state = app.store.state

    run1 = state.runs[first.run.id]
    assert run1.status is RunStatus.COMPLETED, run1.reasons  # done when scraping is done
    assert app.extractor.calls == []
    assert await app.backlog() == 3
    assert state.links[(SEARCH, A)].is_relevant is None  # not classified yet

    assert await app.extract() == 3  # the extractor reconciles afterwards
    state = app.store.state
    assert set(state.offers) == {A, B, C}
    detail_calls = source.detail_call_ids()
    assert sorted(detail_calls, key=str) == [A, B, C]  # each offer enriched exactly once
    assert len(app.jobs(JobType.DISCOVER_PAGE)) == 2
    assert len(app.jobs(JobType.ENRICH_OFFER)) == 3
    assert app.jobs(JobType.EXTRACT_OFFER) == []
    assert len(app.extractor.calls) == 3
    assert await app.backlog() == 0
    assert state.snapshots == []  # first observations are not changes
    assert all(o.has_details and o.content_hash for o in state.offers.values())

    links = {o: state.links[(SEARCH, o)] for o in (A, B, C)}
    assert links[A].is_relevant is True
    assert links[B].is_relevant is True
    assert links[C].is_relevant is False  # charger classified as other

    assert run1.metrics.coverage.pages == 2
    assert run1.metrics.discovery.accepted == 5  # 3 + 2 unique per page
    assert run1.metrics.enrichment.accepted == 3
    assert run1.metrics.extraction.seen == 0  # extraction is not part of a run
    assert run1.metrics.usage.total_tokens == 0
    assert run1.metrics.discovery.fill_rate("price") == 1.0
    extraction = state.extractions[0]
    assert extraction.provenance.profile == "main"
    assert extraction.provenance.catalog_fingerprint == app.catalog.fingerprint
    assert extraction.usage.total_tokens == 120
    assert all(j.status is JobStatus.DONE for j in app.jobs())

    relevant = await app.list_offers(OfferFilter(SEARCH, RelevanceFilter.RELEVANT))
    assert {item.offer.id for item in relevant} == {A, B}

    # ------------------------------------------------------------------ run 2
    app.clock.advance()
    a_before = state.offers[A]
    second = await app.start_run(SEARCH)
    assert second.created
    await app.drain()
    await app.extract()
    state = app.store.state

    assert source.detail_call_ids()[3:] == [B]
    assert state.offers[B].price == Price.fixed(900)
    b_snapshots = [s for s in state.snapshots if s.offer_id == B]
    assert len(b_snapshots) == 1
    assert [c.field for c in b_snapshots[0].changes] == [TrackedField.PRICE]
    assert b_snapshots[0].run_id == second.run.id
    assert [s for s in state.snapshots if s.offer_id != B] == []

    a_after = state.offers[A]
    assert a_after.last_seen_at > a_before.last_seen_at  # unchanged: only last_seen moves
    assert a_after.details_fetched_at == a_before.details_fetched_at
    assert state.links[(SEARCH, A)].last_seen_at == a_after.last_seen_at
    assert state.links[(SEARCH, A)].first_seen_at == a_before.first_seen_at

    assert len(app.extractor.calls) == 3  # price is not content: no new LLM call
    run2 = state.runs[second.run.id]
    assert run2.status is RunStatus.COMPLETED
    assert run2.metrics.enrichment.accepted == 1
    assert run2.metrics.extraction.seen == 0


async def test_detail_complete_source_skips_enrichment() -> None:
    """OLX's search API returns full offers: no EnrichOffer, extraction straight away."""
    app = App()
    source = app.add_source("olx_api")
    url = "https://www.olx.pl/api/v1/offers/?query=laptop"
    x = details("X", source="olx_api", title="Laptop Lenovo")
    y = details("Y", source="olx_api", title="Etui na telefon")
    first_page = SearchPageResult(FetchOutcome.OK, observations=(x, y, x))
    changed = details("Y", source="olx_api", title="Etui na telefon", description="Nowy opis")
    second_page = SearchPageResult(FetchOutcome.OK, observations=(x, changed))
    source.script_page(url, first_page, second_page)
    name = SearchName("api-laptops")
    await app.add_search(name, SourceId("olx_api"), url, LAPTOP)

    await app.start_run(name)
    await app.drain()
    assert await app.extract() == 2
    state = app.store.state
    assert source.detail_calls == []
    assert app.jobs(JobType.ENRICH_OFFER) == []
    assert state.links[(name, x.offer_id)].is_relevant is True
    assert state.links[(name, y.offer_id)].is_relevant is False

    app.clock.advance()
    run = await app.start_run(name)
    await app.drain()
    assert await app.backlog() == 1  # Y's content changed: back in the backlog by itself
    await app.extract()
    state = app.store.state
    assert source.detail_calls == []
    assert len(app.extractor.calls) == 3  # only Y, whose content changed
    assert app.extractor.calls[-1].offer_id == y.offer_id
    (snapshot,) = state.snapshots
    assert snapshot.offer_id == y.offer_id
    assert [c.field for c in snapshot.changes] == [TrackedField.DESCRIPTION]
    assert state.runs[run.run.id].status is RunStatus.COMPLETED


async def test_start_run_is_idempotent_while_running() -> None:
    app = App()
    await setup_enrichment_search(app)
    first = await app.start_run(SEARCH)
    again = await app.start_run(SEARCH)
    assert first.created
    assert not again.created
    assert again.run.id == first.run.id
    assert len(app.jobs(JobType.DISCOVER_PAGE)) == 1


async def test_shared_offer_is_classified_once_for_two_searches() -> None:
    app = App()
    source = await setup_enrichment_search(app)
    other = SearchName("cheap-laptops")
    await app.add_search(other, OLX, URL + "?cheap", LAPTOP)
    only_a = SearchPageResult(FetchOutcome.OK, observations=(listing("A", title=TITLES["A"]),))
    source.script_page(URL + "?cheap", only_a)
    await app.start_run(SEARCH)
    await app.drain()
    await app.extract()
    await app.start_run(other)
    await app.drain()
    await app.extract()
    assert len(app.extractor.calls) == 3
    link = app.store.state.links[(other, A)]
    assert link.is_relevant is True  # derived from the existing extraction at link time

"""Use cases other than the pipeline flow, and fakes-vs-ports conformance."""

from __future__ import annotations

import pytest

from scrappy.application.errors import ConflictError, InvalidRequestError, NotFoundError
from scrappy.application.jobs.model import JobType
from scrappy.application.policy import DiscoveryPolicy, PipelinePolicy
from scrappy.application.ports.extractor import AttributeExtractor
from scrappy.application.ports.job_queue import JobQueue
from scrappy.application.ports.listing_source import (
    ListingSource,
    OfferDetailsResult,
    PageRef,
    SearchPageResult,
)
from scrappy.application.ports.queries import OfferFilter, OfferQueries, RelevanceFilter
from scrappy.application.ports.system import CategoryProvider, Clock, IdGenerator
from scrappy.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.offer import OfferStatus
from scrappy.domain.run import RunStatus
from scrappy.domain.search import SearchName
from scrappy.domain.shared import FetchOutcome, InvalidValueError, RunId, SourceId
from tests.unit.application.harness import App, classify_by_title
from tests.unit.builders import LAPTOP, catalog, details, listing, oid
from tests.unit.fakes import (
    FakeClock,
    InMemoryOfferQueries,
    InMemoryStore,
    ScriptedExtractor,
    ScriptedListingSource,
    SequentialIds,
    StaticCategoryProvider,
)
from tests.unit.fakes.store import InMemoryJobQueue, StoreState

SEARCH = SearchName("gtx-laptops")
URL = "https://www.olx.pl/oferty/q-gtx/"
OLX = SourceId("olx_pl")


def test_fakes_implement_the_ports() -> None:
    """Static check (pyright): every fake is assignable to its port."""
    store = InMemoryStore()
    uow_factory: UnitOfWorkFactory = store.uow
    uow: UnitOfWork = uow_factory()
    queue: JobQueue = InMemoryJobQueue(StoreState())
    source: ListingSource = ScriptedListingSource("olx_pl")
    extractor: AttributeExtractor = ScriptedExtractor(classify_by_title)
    queries: OfferQueries = InMemoryOfferQueries(store)
    categories: CategoryProvider = StaticCategoryProvider(catalog())
    clock: Clock = FakeClock()
    ids: IdGenerator = SequentialIds()
    ports = (uow, queue, source, extractor, queries, categories, clock, ids)
    assert all(port is not None for port in ports)


async def ready_app(policy: PipelinePolicy | None = None) -> tuple[App, ScriptedListingSource]:
    app = App(policy=policy or PipelinePolicy())
    source = app.add_source("olx_pl")
    await app.add_search(SEARCH, OLX, URL, LAPTOP)
    return app, source


class TestAddSavedSearch:
    async def test_idempotent_for_same_definition(self) -> None:
        app, _ = await ready_app()
        again = await app.add_search(SEARCH, OLX, URL, LAPTOP)
        assert not again.created

    async def test_conflict_for_different_definition(self) -> None:
        app, _ = await ready_app()
        with pytest.raises(ConflictError):
            await app.add_search(SEARCH, OLX, URL + "x", LAPTOP)

    @pytest.mark.parametrize(
        ("source", "category"),
        [("allegro_pl", "laptop"), ("olx_pl", "tv"), ("olx_pl", "other")],
    )
    async def test_unknown_source_or_category(self, source: str, category: str) -> None:
        app, _ = await ready_app()
        with pytest.raises(InvalidRequestError):
            await app.add_search(SearchName("x"), SourceId(source), URL, CategoryName(category))

    async def test_source_rejects_unsupported_url_before_anything_is_stored(self) -> None:
        app, source = await ready_app()
        source.rejected_urls["https://example.test/bad"] = "unsupported search URL"
        with pytest.raises(InvalidRequestError, match="unsupported"):
            await app.add_search(SearchName("bad"), OLX, "https://example.test/bad", LAPTOP)
        async with app.store.uow() as uow:
            assert await uow.searches.get(SearchName("bad")) is None

    async def test_url_is_validated_by_the_searchs_own_source(self) -> None:
        app, source = await ready_app()
        await app.add_search(SearchName("ok"), OLX, "https://example.test/ok", LAPTOP)
        assert "https://example.test/ok" in source.validated_urls


class TestRuns:
    async def test_start_unknown_search(self) -> None:
        app, _ = await ready_app()
        with pytest.raises(NotFoundError):
            await app.start_run(SearchName("nope"))

    async def test_resume_unknown_run(self) -> None:
        app, _ = await ready_app()
        with pytest.raises(NotFoundError):
            await app.resume_run(RunId("nope"))

    async def test_resume_finished_run_without_failures_is_a_no_op(self) -> None:
        app, _ = await ready_app()
        started = await app.start_run(SEARCH)
        await app.drain()
        resumed = await app.resume_run(started.run.id)
        assert resumed.requeued == 0
        assert resumed.run.status is RunStatus.COMPLETED

    async def test_empty_search_completes(self) -> None:
        app, _ = await ready_app()
        started = await app.start_run(SEARCH)
        await app.drain()
        run = app.store.state.runs[started.run.id]
        assert run.status is RunStatus.COMPLETED
        assert run.metrics.discovery.accepted == 0

    async def test_pagination_loop_is_stopped_by_dedup(self) -> None:
        app, source = await ready_app()
        source.script_page(URL, SearchPageResult(FetchOutcome.OK, next_page=PageRef("p2", 2)))
        source.script_page("p2", SearchPageResult(FetchOutcome.OK, next_page=PageRef(URL, 3)))
        await app.start_run(SEARCH)
        await app.drain()
        assert len(source.page_calls) == 2

    async def test_max_pages_cap_marks_run_truncated(self) -> None:
        app, source = await ready_app(PipelinePolicy(discovery=DiscoveryPolicy(max_pages=1)))
        source.script_page(
            URL,
            SearchPageResult(
                FetchOutcome.OK, observations=(details("1"),), next_page=PageRef("p2", 2)
            ),
        )
        started = await app.start_run(SEARCH)
        await app.drain()
        run = app.store.state.runs[started.run.id]
        assert run.metrics.coverage.truncated
        assert run.warnings
        assert len(source.page_calls) == 1

    async def test_source_reported_truncation_reaches_the_run(self) -> None:
        app, source = await ready_app()
        page = SearchPageResult(
            FetchOutcome.OK, observations=(details("1"),), total_results=1000, truncated=True
        )
        source.script_page(URL, page)
        started = await app.start_run(SEARCH)
        await app.drain()
        run = app.store.state.runs[started.run.id]
        assert run.metrics.coverage.total_reported == 1000
        assert "split the search" in run.warnings[0]


class TestExtractionTriggers:
    async def test_scraping_never_queues_extraction_the_backlog_heals(self) -> None:
        app, source = await ready_app()
        source.script_page(URL, SearchPageResult(FetchOutcome.OK, observations=(details("1"),)))
        await app.start_run(SEARCH)
        await app.drain()
        assert app.jobs(JobType.EXTRACT_OFFER) == []
        assert app.extractor.calls == []
        assert await app.backlog() == 1

        await app.extract()
        assert len(app.extractor.calls) == 1
        assert app.store.state.links[(SEARCH, oid("1"))].is_relevant is True
        assert await app.backlog() == 0  # up to date now
        await app.extract()
        assert len(app.extractor.calls) == 1

    async def test_schema_bump_re_extracts_automatically(self) -> None:
        app, source = await ready_app()
        page = SearchPageResult(
            FetchOutcome.OK,
            observations=(details("1"), details("2", title="Etui", description="Etui")),
        )
        source.script_page(URL, page)
        await app.start_run(SEARCH)
        await app.drain()
        await app.extract()
        assert len(app.extractor.calls) == 2

        # a new catalog is a new extraction context for every offer (ADR 0010 section 2)
        app.categories.current = catalog(laptop_version=2)
        assert await app.backlog() == 2
        await app.extract()
        assert {c.offer_id for c in app.extractor.calls[2:]} == {oid("1"), oid("2")}
        latest = next(e for e in reversed(app.store.state.extractions) if e.offer_id == oid("1"))
        assert latest.provenance.schema_version == 2

    async def test_force_re_extracts_once(self) -> None:
        app, source = await ready_app()
        source.script_page(URL, SearchPageResult(FetchOutcome.OK, observations=(details("1"),)))
        await app.start_run(SEARCH)
        await app.drain()
        await app.extract()
        result = await app.force_reextract(category=LAPTOP)
        assert result.marked == 1
        assert await app.backlog() == 1
        await app.extract()
        assert len(app.extractor.calls) == 2
        await app.extract()
        assert len(app.extractor.calls) == 2  # the force is consumed by the success


class TestListOffersAndOverride:
    async def populated(self) -> App:
        app, source = await ready_app()
        page = SearchPageResult(
            FetchOutcome.OK,
            observations=(
                details("1", title="Laptop A"),
                details("2", title="Etui", description="Etui"),
                listing("3", title="Laptop B"),
            ),
        )
        source.script_page(URL, page)
        source.script_details(oid("3"), OfferDetailsResult.gone(OfferStatus.SOLD))
        await app.start_run(SEARCH)
        await app.drain()
        await app.extract()
        return app

    async def test_relevance_filters(self) -> None:
        app = await self.populated()

        async def ids(relevance: RelevanceFilter) -> set[str]:
            items = await app.list_offers(OfferFilter(SEARCH, relevance))
            return {i.offer.id.external_id for i in items}

        assert await ids(RelevanceFilter.ALL) == {"1", "2", "3"}
        assert await ids(RelevanceFilter.RELEVANT) == {"1"}
        assert await ids(RelevanceFilter.IRRELEVANT) == {"2"}
        assert await ids(RelevanceFilter.NOT_IRRELEVANT) == {"1", "3"}  # 3 never classified

    async def test_status_and_attribute_filters(self) -> None:
        app = await self.populated()
        sold = await app.list_offers(OfferFilter(SEARCH, statuses=frozenset({OfferStatus.SOLD})))
        assert [i.offer.id.external_id for i in sold] == ["3"]

        ram = AttributePredicate("ram_gb", Comparison.GE, "16")  # coerced to int by the use case
        items = await app.list_offers(OfferFilter(SEARCH, attributes=(ram,)))
        assert [i.offer.id.external_id for i in items] == ["1"]
        too_much = AttributePredicate("ram_gb", Comparison.GT, 16)
        assert await app.list_offers(OfferFilter(SEARCH, attributes=(too_much,))) == []

    async def test_attribute_filter_validation(self) -> None:
        app = await self.populated()
        with pytest.raises(InvalidRequestError):
            await app.list_offers(
                OfferFilter(SEARCH, attributes=(AttributePredicate("x", Comparison.EQ, 1),))
            )
        bad = AttributePredicate("ram_gb", Comparison.EQ, "lots")
        with pytest.raises(InvalidRequestError):
            await app.list_offers(OfferFilter(SEARCH, attributes=(bad,)))
        gpu = AttributePredicate("gpu", Comparison.GT, "a")
        with pytest.raises(InvalidRequestError):
            await app.list_offers(OfferFilter(SEARCH, attributes=(gpu,)))
        with pytest.raises(InvalidRequestError):
            await app.list_offers(
                OfferFilter(attributes=(AttributePredicate("gpu", Comparison.EQ, "a"),))
            )
        with pytest.raises(InvalidValueError):
            OfferFilter(relevance=RelevanceFilter.RELEVANT)
        with pytest.raises(NotFoundError):
            await app.list_offers(OfferFilter(SearchName("nope")))

    async def test_override(self) -> None:
        app = await self.populated()
        link = await app.set_override(SEARCH, oid("2"), True)
        assert link.is_relevant is True
        items = await app.list_offers(OfferFilter(SEARCH, RelevanceFilter.RELEVANT))
        assert {i.offer.id.external_id for i in items} == {"1", "2"}
        with pytest.raises(NotFoundError):
            await app.set_override(SEARCH, oid("missing"), True)

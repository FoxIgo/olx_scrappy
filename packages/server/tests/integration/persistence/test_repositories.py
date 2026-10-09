"""Repository round-trips and transaction behaviour of the SQL unit of work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import (
    ExtractionProvenance,
    OfferExtraction,
    TokenUsage,
)
from scrappy.domain.offer import (
    ContentHash,
    FieldChange,
    Offer,
    OfferSnapshot,
    OfferStatus,
    Params,
    Price,
    SellerRef,
    TrackedField,
)
from scrappy.domain.run import (
    DiscoveryCoverage,
    PhaseMetrics,
    RunConclusion,
    RunMetrics,
    RunStatus,
    ScrapeRun,
)
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import FetchOutcome, Money, RunId, SourceId
from scrappy.infrastructure.persistence.engine import READ_ONLY_OPTION
from tests.integration.persistence.sqlstore import SqlStore
from tests.unit.builders import LAPTOP, T0, at, oid

SEARCH = SearchName("gtx-laptops")
OLX = SourceId("olx_pl")
HASH = ContentHash("ab" * 32)

type Factory = Callable[[], UnitOfWork]


def saved_search(name: str = "gtx-laptops") -> SavedSearch:
    return SavedSearch(SearchName(name), OLX, f"https://www.olx.pl/{name}/", LAPTOP, T0)


def full_offer(external_id: str = "1") -> Offer:
    return Offer(
        id=oid(external_id),
        url="https://www.olx.pl/d/oferta/1",
        first_seen_at=T0,
        last_seen_at=at(5),
        title="Laptop Dell zażółć gęślą jaźń",
        price=Price.fixed(Money.of(Decimal("1234.50"), "PLN"), negotiable=True),
        location="Kraków",
        thumbnail_url="https://img.test/1.jpg",
        posted_at=datetime(2026, 9, 30, 8, 15, tzinfo=timezone(timedelta(hours=2))),
        refreshed_at=at(1),
        description="Gaming laptop, GTX 1650",
        params=Params.of({"state": "used", "marka": "Dell"}),
        status=OfferStatus.ACTIVE,
        seller=SellerRef("s-1", "Jan", True),
        image_urls=("https://img.test/1.jpg", "https://img.test/2.jpg"),
        content_hash=HASH,
        details_fetched_at=at(2),
    )


def same(a: object, b: object) -> None:
    assert asdict(a) == asdict(b)  # pyright: ignore[reportArgumentType]


def extraction(
    external_id: str = "1",
    *,
    category: str = "laptop",
    attributes: dict[str, object] | None = None,
    minutes: int = 0,
    model: str = "m",
) -> OfferExtraction:
    return OfferExtraction(
        offer_id=oid(external_id),
        category=CategoryName(category),
        attributes=attributes if attributes is not None else {"gpu": "GTX 1650"},  # pyright: ignore[reportArgumentType]
        provenance=ExtractionProvenance(model, "p1", 1, HASH, at(minutes)),
        usage=TokenUsage(100, 20, Decimal("0.000123")),
        notes="n",
    )


async def seed(factory: Factory, *offers: Offer) -> None:
    async with factory() as uow:
        await uow.searches.save(saved_search())
        for offer in offers:
            await uow.offers.save(offer)
        await uow.commit()


class TestOffers:
    async def test_full_round_trip_keeps_precision_and_timezones(self, uow: Factory) -> None:
        offer = full_offer()
        async with uow() as unit:
            await unit.offers.save(offer)
            await unit.commit()
        async with uow() as unit:
            loaded = await unit.offers.get(offer.id)
        assert loaded is not None
        same(loaded, offer)
        assert loaded.price is not None and loaded.price.amount is not None
        assert str(loaded.price.amount.amount) == "1234.50"  # trailing zero kept
        assert loaded.posted_at == offer.posted_at
        assert loaded.posted_at is not None and loaded.posted_at.utcoffset() == timedelta(0)

    @pytest.mark.parametrize(
        "price",
        [None, Price.exchange(), Price.free(), Price.fixed("0.01", "EUR"), Price.fixed(10**12)],
    )
    async def test_price_kinds(self, uow: Factory, price: Price | None) -> None:
        offer = full_offer()
        offer.price = price
        await seed(uow, offer)
        async with uow() as unit:
            loaded = await unit.offers.get(offer.id)
        assert loaded is not None and loaded.price == price

    async def test_sparse_offer_and_params_none_vs_empty(self, uow: Factory) -> None:
        sparse = Offer(oid("2"), "https://x.test/2", T0, T0)
        empty = Offer(oid("3"), "https://x.test/3", T0, T0, params=Params())
        await seed(uow, sparse, empty)
        async with uow() as unit:
            loaded_sparse = await unit.offers.get(sparse.id)
            loaded_empty = await unit.offers.get(empty.id)
        assert loaded_sparse is not None and loaded_empty is not None
        same(loaded_sparse, sparse)
        assert loaded_sparse.params is None
        assert loaded_empty.params == Params()
        assert loaded_sparse.seller is None and loaded_sparse.image_urls == ()

    async def test_save_is_an_upsert_and_copies_do_not_write_through(self, uow: Factory) -> None:
        offer = full_offer()
        await seed(uow, offer)
        async with uow() as unit:
            loaded = await unit.offers.get(offer.id)
            assert loaded is not None
            loaded.title = "changed but never saved"
            again = await unit.offers.get(offer.id)
            assert again is not None and again.title == offer.title
            offer.title = "saved"
            await unit.offers.save(offer)
            await unit.offers.save(offer)  # idempotent
            await unit.commit()
        async with uow() as unit:
            final = await unit.offers.get(offer.id)
            assert final is not None and final.title == "saved"
            assert await unit.offers.get(oid("missing")) is None

    async def test_get_many_returns_only_existing(self, uow: Factory) -> None:
        await seed(uow, full_offer("1"), full_offer("2"))
        async with uow() as unit:
            found = await unit.offers.get_many([oid("1"), oid("2"), oid("3"), oid("1")])
            assert set(found) == {oid("1"), oid("2")}
            assert await unit.offers.get_many([]) == {}

    async def test_get_many_chunks_large_requests(self, uow: Factory) -> None:
        offers = [full_offer(str(i)) for i in range(1000)]
        async with uow() as unit:
            await unit.searches.save(saved_search())
            for offer in offers:
                await unit.offers.save(offer)
            await unit.commit()
        async with uow() as unit:
            found = await unit.offers.get_many([o.id for o in offers] + [oid("nope")])
        assert len(found) == 1000

    async def test_list_with_content_is_a_keyset_page_in_string_order(self, uow: Factory) -> None:
        offers = [full_offer(i) for i in ("b", "10", "a", "2")]
        no_content = Offer(oid("zz"), "https://x.test/zz", T0, T0)
        other_source = Offer(
            oid("1", source="allegro_pl"), "https://x.test/a", T0, T0, content_hash=HASH
        )
        await seed(uow, *offers, no_content, other_source)
        async with uow() as unit:
            page1 = await unit.offers.list_with_content(after=None, limit=3)
            assert [str(o.id) for o in page1] == ["allegro_pl:1", "olx_pl:10", "olx_pl:2"]
            page2 = await unit.offers.list_with_content(after=page1[-1].id, limit=3)
            assert [str(o.id) for o in page2] == ["olx_pl:a", "olx_pl:b"]
            assert await unit.offers.list_with_content(after=page2[-1].id, limit=3) == []

    async def test_snapshots_keep_changes_with_types_in_order(self, uow: Factory) -> None:
        offer = full_offer()
        await seed(uow, offer)
        first = OfferSnapshot(
            offer.id,
            at(3),
            (
                FieldChange(TrackedField.TITLE, "old", "new"),
                FieldChange(TrackedField.PRICE, Price.fixed("10.10"), Price.exchange()),
                FieldChange(TrackedField.PARAMS, Params.of({"a": "1"}), Params()),
                FieldChange(TrackedField.STATUS, OfferStatus.ACTIVE, OfferStatus.SOLD),
            ),
            RunId("run1"),
        )
        second = OfferSnapshot(
            offer.id, at(1), (FieldChange(TrackedField.LOCATION, "a", "b"),)
        )  # older timestamp, inserted later: list is by insertion (like the fake)
        async with uow() as unit:
            await unit.offers.add_snapshot(first)
            await unit.offers.add_snapshot(second)
            await unit.offers.add_snapshot(first)  # never deduplicated
            await unit.commit()
        async with uow() as unit:
            loaded = await unit.offers.list_snapshots(offer.id)
            assert await unit.offers.list_snapshots(oid("other")) == []
        assert len(loaded) == 3
        same(loaded[0], first)
        same(loaded[1], second)
        assert loaded[1].run_id is None


class TestSearchesAndLinks:
    async def test_saved_searches_round_trip_and_order(self, uow: Factory) -> None:
        later = saved_search("b-search")
        later.last_run_at = at(9)
        async with uow() as unit:
            await unit.searches.save(later)
            await unit.searches.save(saved_search("a-search"))
            await unit.commit()
        async with uow() as unit:
            names = [s.name.value for s in await unit.searches.list_all()]
            loaded = await unit.searches.get(SearchName("b-search"))
            assert await unit.searches.get(SearchName("nope")) is None
        assert names == ["a-search", "b-search"]
        assert loaded is not None
        same(loaded, later)

    async def test_links_upsert_override_and_listing(self, uow: Factory) -> None:
        await seed(uow, full_offer("1"), full_offer("2"))
        other = SearchName("another")
        async with uow() as unit:
            await unit.searches.save(saved_search("another"))
            link = SearchOffer.first_seen(SEARCH, oid("1"), T0)
            link.derived_relevance = True
            await unit.search_offers.save(link)
            await unit.search_offers.save(SearchOffer.first_seen(other, oid("1"), at(1)))
            await unit.search_offers.save(SearchOffer.first_seen(SEARCH, oid("2"), at(1)))
            await unit.commit()
        async with uow() as unit:
            link = await unit.search_offers.get(SEARCH, oid("1"))
            assert link is not None and link.is_relevant is True
            link.set_override(False)
            link.mark_seen(at(7))
            await unit.search_offers.save(link)
            await unit.commit()
        async with uow() as unit:
            link = await unit.search_offers.get(SEARCH, oid("1"))
            assert link is not None
            assert (link.derived_relevance, link.relevance_override) == (True, False)
            assert link.is_relevant is False
            assert link.last_seen_at == at(7)
            many = await unit.search_offers.get_many(SEARCH, [oid("1"), oid("2"), oid("3")])
            assert set(many) == {oid("1"), oid("2")}
            assert await unit.search_offers.get(SEARCH, oid("3")) is None
            for_offer = await unit.search_offers.list_for_offer(oid("1"))
            assert [(x.search.value) for x in for_offer] == ["another", "gtx-laptops"]
            assert [x.search.value for x in await unit.search_offers.list_for_offer(oid("2"))] == [
                "gtx-laptops"
            ]


class TestExtractions:
    async def test_attribute_types_survive(self, uow: Factory) -> None:
        await seed(uow, full_offer())
        attributes: dict[str, object] = {
            "gpu": "GTX 1650",
            "ram_gb": 16,
            "screen_in": Decimal("15.60"),
            "ssd": True,
            "hdd": False,
            "note": None,
            "big": 10**15,
        }
        original = extraction(attributes=attributes)
        async with uow() as unit:
            await unit.extractions.add(original)
            await unit.commit()
        async with uow() as unit:
            loaded = await unit.extractions.latest(oid("1"))
        assert loaded is not None
        same(loaded, original)
        assert type(loaded.attributes["ram_gb"]) is int
        assert type(loaded.attributes["screen_in"]) is Decimal
        assert str(loaded.attributes["screen_in"]) == "15.60"
        assert loaded.attributes["ssd"] is True and loaded.attributes["hdd"] is False
        assert loaded.usage.cost_usd == Decimal("0.000123")

    async def test_other_category_and_missing_cost(self, uow: Factory) -> None:
        await seed(uow, full_offer())
        other = OfferExtraction(
            oid("1"),
            CategoryName("other"),
            {},
            ExtractionProvenance("m", "p1", None, HASH, at(0)),
        )
        async with uow() as unit:
            await unit.extractions.add(other)
            await unit.commit()
        async with uow() as unit:
            loaded = await unit.extractions.latest(oid("1"))
        assert loaded is not None
        assert loaded.provenance.schema_version is None and loaded.usage.cost_usd is None
        same(loaded, other)

    async def test_latest_is_newest_then_last_inserted(self, uow: Factory) -> None:
        await seed(uow, full_offer("1"), full_offer("2"))
        async with uow() as unit:
            await unit.extractions.add(extraction("1", minutes=5, model="newest"))
            await unit.extractions.add(extraction("1", minutes=1, model="older-inserted-later"))
            await unit.extractions.add(extraction("2", minutes=2, model="first"))
            await unit.extractions.add(extraction("2", minutes=2, model="tie-last-wins"))
            await unit.commit()
        async with uow() as unit:
            latest = await unit.extractions.latest_many([oid("1"), oid("2"), oid("3")])
            assert {k: v.provenance.model for k, v in latest.items()} == {
                oid("1"): "newest",
                oid("2"): "tie-last-wins",
            }
            single = await unit.extractions.latest(oid("2"))
            assert single is not None and single.provenance.model == "tie-last-wins"
            assert await unit.extractions.latest(oid("3")) is None


class TestRuns:
    def run(self, run_id: str, started: datetime, search: str = "gtx-laptops") -> ScrapeRun:
        return ScrapeRun(RunId(run_id), SearchName(search), OLX, started)

    async def test_round_trip_with_metrics(self, uow: Factory) -> None:
        metrics = RunMetrics(
            discovery=PhaseMetrics(
                accepted=5,
                rejected=1,
                present={"price": 5},
                applicable={"price": 5, "title": 5},
                outcomes={FetchOutcome.OK: 2, FetchOutcome.BLOCKED: 1},
            ),
            usage=TokenUsage(10, 5, Decimal("0.0042")),
            coverage=DiscoveryCoverage(2, 1000, True),
            failed_jobs=1,
        )
        run = self.run("r1", T0)
        run.finish(
            RunConclusion(RunStatus.PARTIAL, ("some failed",), ("slow",)), metrics, at(3), ("boom",)
        )
        async with uow() as unit:
            await unit.searches.save(saved_search())
            await unit.runs.save(run)
            await unit.commit()
        async with uow() as unit:
            loaded = await unit.runs.get(RunId("r1"))
            assert await unit.runs.get(RunId("nope")) is None
        assert loaded is not None
        same(loaded, run)
        assert loaded.metrics.usage.cost_usd == Decimal("0.0042")

    async def test_find_running_reopen_and_listing_order(self, uow: Factory) -> None:
        async with uow() as unit:
            await unit.searches.save(saved_search())
            await unit.searches.save(saved_search("other"))
            for run_id, minutes in (("r1", 1), ("r2", 5), ("r3", 5), ("r4", 3)):
                await unit.runs.save(self.run(run_id, at(minutes)))
            await unit.runs.save(self.run("x", at(9), search="other"))
            await unit.commit()
        async with uow() as unit:
            running = await unit.runs.find_running(SEARCH)
            assert running is not None and running.id == RunId("r1")  # first inserted
            run = await unit.runs.get(RunId("r1"))
            assert run is not None
            run.finish(RunConclusion(RunStatus.COMPLETED), RunMetrics(), at(10))
            await unit.runs.save(run)
            running = await unit.runs.find_running(SEARCH)
            assert running is not None and running.id == RunId("r2")
            listed = await unit.runs.list_for_search(SEARCH, limit=3)
            # newest first, ties in insertion order (stable like the fake)
            assert [r.id.value for r in listed] == ["r2", "r3", "r4"]
            assert await unit.runs.find_running(SearchName("nobody")) is None
            run.reopen()
            await unit.runs.save(run)
            reopened = await unit.runs.get(RunId("r1"))
            assert reopened is not None and reopened.is_running and reopened.finished_at is None
            assert [r.id.value for r in await unit.runs.list_for_search(SEARCH, limit=10)] == [
                "r2",
                "r3",
                "r4",
                "r1",
            ]


class TestTransactions:
    async def test_without_commit_everything_is_discarded(self, uow: Factory) -> None:
        async with uow() as unit:
            await unit.searches.save(saved_search())
            await unit.offers.save(full_offer())
            assert await unit.offers.get(oid("1")) is not None  # visible inside
        async with uow() as unit:
            assert await unit.offers.get(oid("1")) is None
            assert await unit.searches.list_all() == []

    async def test_exception_rolls_back_even_after_a_commit_of_earlier_work(
        self, uow: Factory
    ) -> None:
        async with uow() as unit:
            await unit.searches.save(saved_search("kept"))
            await unit.commit()
            await unit.searches.save(saved_search("lost"))
        async with uow() as unit:
            assert [s.name.value for s in await unit.searches.list_all()] == ["kept"]

    async def test_explicit_rollback_then_continue(self, uow: Factory) -> None:
        async with uow() as unit:
            await unit.searches.save(saved_search("a"))
            await unit.rollback()
            assert await unit.searches.list_all() == []
            await unit.searches.save(saved_search("b"))
            await unit.commit()
        async with uow() as unit:
            assert [s.name.value for s in await unit.searches.list_all()] == ["b"]

    async def test_uncommitted_writes_are_invisible_to_other_connections(
        self, store: SqlStore
    ) -> None:
        async def count() -> int:
            async with store.engine.connect() as conn:
                await conn.execution_options(**{READ_ONLY_OPTION: True})
                result = await conn.execute(text("select count(*) from saved_searches"))
                return int(result.scalar_one())

        async with store.uow() as writer:
            await writer.searches.save(saved_search())
            assert await count() == 0  # a WAL reader neither sees it nor is blocked
            await writer.commit()
        assert await count() == 1

    async def test_unit_of_work_is_single_use_and_needs_a_block(self, uow: Factory) -> None:
        unit = uow()
        with pytest.raises(RuntimeError):
            _ = unit.offers
        async with unit:
            pass
        with pytest.raises(RuntimeError):
            async with unit:
                pass

    async def test_naive_datetimes_are_rejected(self, uow: Factory) -> None:
        offer = full_offer()
        offer.last_seen_at = datetime(2026, 1, 1)
        async with uow() as unit:
            with pytest.raises(Exception, match=r"(?i)naive|timezone"):
                await unit.offers.save(offer)

    async def test_foreign_keys_are_enforced_at_commit(self, uow: Factory) -> None:
        snapshot = OfferSnapshot(oid("ghost"), T0, (FieldChange(TrackedField.TITLE, "a", "b"),))
        async with uow() as unit:
            await unit.offers.add_snapshot(snapshot)  # deferred: accepted until commit
            with pytest.raises(IntegrityError):
                await unit.commit()

    async def test_utc_conversion_of_offsets(self, uow: Factory) -> None:
        plus3 = timezone(timedelta(hours=3))
        offer = full_offer()
        offer.first_seen_at = datetime(2026, 10, 1, 15, 0, tzinfo=plus3)
        await seed(uow, offer)
        async with uow() as unit:
            loaded = await unit.offers.get(offer.id)
        assert loaded is not None
        assert loaded.first_seen_at == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        assert loaded.first_seen_at.tzinfo is UTC

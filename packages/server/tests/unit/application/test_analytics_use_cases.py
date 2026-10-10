"""The ``q`` use cases over the in-memory fakes."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.ports.analytics import SqlResult
from scrappy.application.use_cases.analytics import (
    QueryScope,
    QueryUseCases,
    build_query_use_cases,
)
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import (
    AttributePredicate,
    Comparison,
    ExtractionProvenance,
    OfferExtraction,
)
from scrappy.domain.offer import (
    ContentHash,
    FieldChange,
    Offer,
    OfferSnapshot,
    OfferStatus,
    Price,
    TrackedField,
)
from scrappy.domain.run import RunStatus, ScrapeRun
from scrappy.domain.scoring import Strategy
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import RunId, SourceId
from tests.unit.builders import LAPTOP, T0, at, catalog, oid
from tests.unit.fakes import (
    InMemoryAnalyticsQueries,
    InMemoryScoringQueries,
    InMemoryStore,
    StaticCategoryProvider,
    StaticScoringProvider,
)

S = SearchName("laptops")
HASH = ContentHash("a" * 64)


class World:
    def __init__(self, strategies: Mapping[str, Strategy] | None = None) -> None:
        self.store = InMemoryStore()
        self.queries = InMemoryAnalyticsQueries(self.store)
        self.scoring_queries = InMemoryScoringQueries()
        self.q: QueryUseCases = build_query_use_cases(
            uow=self.store.uow,
            queries=self.queries,
            categories=StaticCategoryProvider(catalog()),
            scoring=StaticScoringProvider(strategies or {}),
            scoring_queries=self.scoring_queries,
        )
        self.store.state.searches[S] = SavedSearch(
            S, SourceId("olx_pl"), "https://x.test", LAPTOP, T0
        )

    def add(
        self,
        key: str,
        price: Price | None,
        attributes: dict[str, Any] | None = None,
        *,
        category: str = "laptop",
        relevant: bool | None = True,
        status: OfferStatus = OfferStatus.ACTIVE,
        title: str = "Laptop",
        minutes: int = 0,
    ) -> None:
        state = self.store.state
        offer = Offer(
            id=oid(key),
            url=f"https://x.test/{key}",
            first_seen_at=at(minutes),
            last_seen_at=at(minutes),
            title=title,
            price=price,
            status=status,
        )
        state.offers[offer.id] = offer
        link = SearchOffer.first_seen(S, offer.id, at(minutes))
        link.derived_relevance = relevant
        state.links[(S, offer.id)] = link
        if attributes is not None:
            state.extractions.append(
                OfferExtraction(
                    offer_id=offer.id,
                    category=CategoryName(category),
                    attributes=attributes,
                    provenance=ExtractionProvenance("m", "p1", 1, HASH, at(minutes)),
                )
            )


def scope(**kwargs: Any) -> QueryScope:
    return QueryScope(search=S, **kwargs)


def where(attribute: str, op: Comparison, value: str) -> AttributePredicate:
    return AttributePredicate(attribute, op, value)


@pytest.fixture
def world() -> World:
    w = World()
    for i, price in enumerate(["900", "1000", "1000", "1000", "1100", "400"]):
        w.add(f"a{i}", Price.fixed(price), {"gpu": "GTX 1650", "ram_gb": 16}, minutes=i)
    w.add("b1", Price.fixed("2000"), {"gpu": "RTX 3060", "ram_gb": 32}, minutes=10)
    w.add("b2", Price.fixed("2100"), {"gpu": "RTX 3060", "ram_gb": 32}, minutes=11)
    w.add("eur", Price.fixed("300", "EUR"), {"gpu": "GTX 1650", "ram_gb": 16}, minutes=12)
    w.add("free", Price.free(), {"gpu": "GTX 1650", "ram_gb": 16}, minutes=13)
    w.add("nogpu", Price.fixed("500"), {"gpu": None, "ram_gb": 8}, minutes=14)
    w.add("raw", Price.fixed("700"), None, minutes=15)  # not extracted
    w.add("junk", Price.fixed("5"), {"gpu": "x", "ram_gb": 1}, relevant=False, minutes=16)
    w.add("sold", Price.fixed("50"), {"gpu": "x", "ram_gb": 1}, status=OfferStatus.SOLD)
    return w


async def test_offers_filters_projects_and_notes(world: World) -> None:
    answer = await world.q.offers(scope(), limit=3, fields=["id", "price", "ram_gb"])
    assert answer.count == 3
    assert answer.truncated
    first = answer.data[0]  # type: ignore[index]
    assert set(first) == {"id", "price", "attributes"}
    assert first["attributes"] == {"ram_gb": None}  # newest offer ("raw") is not extracted
    assert any("hidden" in n for n in answer.notes)  # junk (and sold? no: status) hidden

    cheap = await world.q.offers(
        scope(where=(where("price", Comparison.LT, "500"), where("ram_gb", Comparison.GE, "16")))
    )
    assert [r["id"] for r in cheap.data] == ["olx_pl:eur", "olx_pl:a5"]  # type: ignore[index,union-attr]

    everything = await world.q.offers(scope(relevant_only=False, statuses=frozenset()), limit=100)
    assert everything.count == 14


async def test_offers_rejects_unknown_field_sort_and_attribute_without_category(
    world: World,
) -> None:
    with pytest.raises(InvalidRequestError, match="unknown field"):
        await world.q.offers(scope(), fields=["nope"])
    with pytest.raises(InvalidRequestError, match="unknown sort"):
        await world.q.offers(scope(), sort="x")
    with pytest.raises(InvalidRequestError, match="need --category or --search"):
        await world.q.offers(QueryScope(where=(where("ram_gb", Comparison.GE, "1"),)))
    with pytest.raises(NotFoundError):
        await world.q.offers(QueryScope(search=SearchName("nope")))
    with pytest.raises(InvalidRequestError, match="has no attribute"):
        await world.q.offers(scope(where=(where("zzz", Comparison.EQ, "1"),)))


async def test_offers_sort_by_price(world: World) -> None:
    answer = await world.q.offers(scope(), sort="price", limit=2)
    assert [r["id"] for r in answer.data] == ["olx_pl:eur", "olx_pl:a5"]  # type: ignore[union-attr]


async def test_facets(world: World) -> None:
    answer = await world.q.facets(scope(), ["gpu", "ram_gb"])
    gpu, ram = answer.data  # type: ignore[misc]
    assert gpu["values"][0] == {"value": "GTX 1650", "count": 8}
    assert gpu["null"] == 1
    assert ram["numeric"]["min"] == Decimal(8)
    assert ram["numeric"]["max"] == Decimal(32)
    assert any("no extraction yet" in n for n in answer.notes)
    with pytest.raises(InvalidRequestError, match="unknown attribute"):
        await world.q.facets(scope(), ["zzz"])
    with pytest.raises(InvalidRequestError, match="at least one"):
        await world.q.facets(scope(), [])


async def test_stats_by_attribute_only_counts_fixed_prices_per_currency(world: World) -> None:
    answer = await world.q.stats(scope(), ["ram_gb"])
    groups: Any = answer.data
    pln16 = next(g for g in groups if g["group"] == {"ram_gb": 16} and g["currency"] == "PLN")
    assert pln16["n"] == 6
    assert pln16["median"] == Decimal("1000.00")
    assert pln16["min"] == Decimal(400)
    assert pln16["max"] == Decimal(1100)
    assert any(g["currency"] == "EUR" for g in groups)
    notes = " | ".join(answer.notes)
    assert "without a fixed price" in notes
    assert "free" in notes
    assert "several currencies" in notes
    assert "no extraction yet" in notes


async def test_stats_overall_and_validation(world: World) -> None:
    overall = await world.q.stats(scope(where=(where("ram_gb", Comparison.EQ, "32"),)))
    assert overall.data[0]["n"] == 2  # type: ignore[index]
    with pytest.raises(InvalidRequestError, match="metric"):
        await world.q.stats(scope(), metric="weight")


async def test_stats_notes_missing_group_attribute(world: World) -> None:
    answer = await world.q.stats(scope(), ["gpu"])
    assert any("lack a value for gpu" in n for n in answer.notes)


async def test_deals_compare_by_attribute(world: World) -> None:
    answer = await world.q.deals(scope(), ["gpu", "ram_gb"], min_group=5)
    deals: Any = answer.data
    assert [d["offer"]["id"] for d in deals] == ["olx_pl:a5"]
    deal = deals[0]
    assert deal["group_size"] == 6
    assert deal["group_median"] == Decimal("1000.00")
    assert deal["ratio"] == Decimal("0.400")
    assert "40%" in deal["reason"]
    assert any("fewer than 5" in n for n in answer.notes)  # RTX group, EUR group
    assert any("lack a value" in n for n in answer.notes)  # nogpu
    with pytest.raises(InvalidRequestError, match="min_group"):
        await world.q.deals(scope(), [], min_group=1)


async def test_deals_none_found_says_so(world: World) -> None:
    answer = await world.q.deals(scope(), ["gpu"], min_group=5, max_ratio=Decimal("0.1"))
    assert answer.data == []
    assert any("no deals" in n for n in answer.notes)


async def test_offer_detail(world: World) -> None:
    state = world.store.state
    state.snapshots.append(
        OfferSnapshot(
            oid("a0"),
            at(30),
            (FieldChange(TrackedField.PRICE, Price.fixed("1000"), Price.fixed("900")),),
            RunId("r1"),
        )
    )
    answer = await world.q.offer(["olx_pl:a0", "olx_pl:missing"])
    detail: Any = answer.data[0]  # type: ignore[index]
    assert detail["extraction"]["attributes"]["ram_gb"] == 16
    assert detail["snapshots"][0]["changes"][0]["new"]["amount"] == Decimal(900)
    assert detail["searches"][0]["relevant"] is True
    assert "olx_pl:missing" in answer.notes[0]
    with pytest.raises(NotFoundError):
        await world.q.offer(["olx_pl:nope"])
    with pytest.raises(InvalidRequestError):
        await world.q.offer(["no-colon"])


async def test_history_changes_new_offers_and_field_filter(world: World) -> None:
    state = world.store.state
    price = FieldChange(TrackedField.PRICE, Price.fixed("1000"), Price.fixed("900"))
    title = FieldChange(TrackedField.TITLE, "a", "b")
    state.snapshots.append(OfferSnapshot(oid("a0"), at(30), (price, title)))
    state.snapshots.append(OfferSnapshot(oid("junk"), at(31), (price,)))  # irrelevant: hidden
    answer = await world.q.history(scope(), since=at(10))
    data: Any = answer.data
    assert {c["field"] for c in data["changes"]} == {"price", "title"}
    assert all(c["offer"] == "olx_pl:a0" for c in data["changes"])
    assert {o["id"] for o in data["new_offers"]} >= {"olx_pl:b1", "olx_pl:raw"}
    assert "olx_pl:a0" not in {o["id"] for o in data["new_offers"]}

    only_price = await world.q.history(scope(), field="price")
    assert [c["field"] for c in only_price.data["changes"]] == ["price"]  # type: ignore[index]
    single = await world.q.history(scope(), offer="olx_pl:junk")
    assert single.count == 1
    with pytest.raises(InvalidRequestError, match="unknown field"):
        await world.q.history(scope(), field="zz")
    with pytest.raises(NotFoundError):
        await world.q.history(scope(), offer="olx_pl:nope")


async def test_health_and_overview(world: World) -> None:
    state = world.store.state
    run = ScrapeRun(RunId("run1"), S, SourceId("olx_pl"), at(100), status=RunStatus.PARTIAL)
    state.runs[run.id] = run
    health = await world.q.health(search=S)
    data: Any = health.data
    assert data["runs"][0]["id"] == "run1"
    assert data["extraction"]["without_extraction"] == 1
    gpu = next(r for r in data["attribute_null_rates"] if r["attribute"] == "gpu")
    assert gpu["null"] == 1
    assert gpu["extracted"] == 13
    assert data["stale"][0]["stale_offers"] > 0
    assert any("partial" in n for n in health.notes)
    with pytest.raises(NotFoundError):
        await world.q.health(search=SearchName("nope"))

    overview: Any = (await world.q.overview()).data
    assert overview["database"] == {"dialect": "sqlite"}
    assert overview["searches"][0]["last_run"]["id"] == "run1"
    assert overview["searches"][0]["offers"]["irrelevant"] == 1
    assert overview["totals"]["offers"] == 14


async def test_schema(world: World) -> None:
    answer = await world.q.schema(category=LAPTOP, tables=True)
    data: Any = answer.data
    assert data["categories"][0]["attributes"][0]["name"] == "gpu"
    assert data["tables"][0]["name"] == "offers"
    with pytest.raises(InvalidRequestError, match="unknown category"):
        await world.q.schema(category=CategoryName("tv"))


async def test_sql_delegates_with_limit_and_notes_truncation(world: World) -> None:
    world.queries.sql_result = SqlResult(("n",), [(1,), (2,)], True)
    answer = await world.q.sql("SELECT 1", limit=2)
    assert answer.data == {"columns": ["n"], "rows": [[1], [2]]}
    assert answer.truncated
    assert world.queries.sql_calls[0][1] == 2
    with pytest.raises(InvalidRequestError):
        await world.q.sql("bad", limit=2)


async def test_export_columns_come_from_the_catalog_and_notes_counts(world: World) -> None:
    table = await world.q.export(scope())
    assert table.columns[:3] == ["offer_id", "source", "title"]
    assert table.columns[-4:] == ["attr_gpu", "attr_ram_gb", "attr_screen_in", "attr_storage_type"]
    assert len(table.rows) == 12
    assert any("12 row(s) exported" in n for n in table.notes)
    mixed = await world.q.export(QueryScope(relevant_only=False))
    assert mixed.columns == table.columns

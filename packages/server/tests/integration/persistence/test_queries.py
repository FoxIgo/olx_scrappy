"""SqlOfferQueries must return exactly what the in-memory reference returns."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from scrappy.application.ports.queries import OfferFilter, OfferListItem, RelevanceFilter
from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.offer import Offer, OfferStatus
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import SourceId
from scrappy.infrastructure.persistence.queries import SqlOfferQueries
from tests.integration.persistence.sqlstore import SqlStore
from tests.integration.persistence.test_repositories import extraction, full_offer
from tests.unit.builders import LAPTOP, PHONE, T0, at, oid
from tests.unit.fakes import InMemoryOfferQueries, InMemoryStore

OLX = SourceId("olx_pl")
S1, S2 = SearchName("laptops"), SearchName("phones")

type Factory = Callable[[], UnitOfWork]


async def populate(factory: Factory) -> None:
    """The same data goes into the fake and into SQL."""
    async with factory() as uow:
        for name, category in ((S1, LAPTOP), (S2, PHONE)):
            await uow.searches.save(SavedSearch(name, OLX, f"https://x.test/{name}", category, T0))

        def offer(key: str, seen: int, status: OfferStatus = OfferStatus.ACTIVE) -> Offer:
            o = full_offer(key)
            o.last_seen_at = at(seen)
            o.status = status
            return o

        offers = [
            offer("1", 10),
            offer("2", 30),
            offer("3", 30),  # ties with 2: ordered by id
            offer("4", 20, OfferStatus.SOLD),
            offer("5", 5, OfferStatus.REMOVED),
            offer("6", 40),
            offer("7", 1),  # no extraction at all
            offer("10", 30),  # sorts before "2" as a string
        ]
        for o in offers:
            await uow.offers.save(o)

        def link(search: SearchName, key: str, seen: int, **kw: bool | None) -> SearchOffer:
            link = SearchOffer.first_seen(search, oid(key), at(seen))
            link.derived_relevance = kw.get("derived")
            link.relevance_override = kw.get("override")
            return link

        links = [
            link(S1, "1", 50, derived=True),
            link(S1, "2", 20, derived=True),
            link(S1, "3", 20, derived=False),
            link(S1, "4", 70, derived=True, override=False),  # override wins
            link(S1, "5", 60, derived=False, override=True),
            link(S1, "6", 5),  # unknown relevance
            link(S1, "7", 6),
            link(S2, "1", 9, derived=False),
            link(S2, "6", 8, derived=True),
        ]
        for lk in links:
            await uow.search_offers.save(lk)

        attrs = {
            "1": ("laptop", {"gpu": "GTX 1650", "ram_gb": 16, "screen_in": Decimal("15.6")}),
            "2": ("laptop", {"gpu": "RTX 3060", "ram_gb": 32, "screen_in": Decimal("17")}),
            "3": (
                "laptop",
                {"gpu": "gtx 1050", "ram_gb": 8, "screen_in": None, "damage": ("screen",)},
            ),
            "4": (
                "laptop",
                {
                    "gpu": None,
                    "ram_gb": 16,
                    "screen_in": Decimal("13.3"),
                    "damage": ("screen", "motherboard"),
                },
            ),
            "5": ("phone", {"model": "iPhone", "new": True}),
            "6": ("phone", {"model": "Galaxy S10", "new": False}),
            "10": ("laptop", {"gpu": "Radeon", "ram_gb": 64}),
        }
        for key, (category, values) in attrs.items():
            await uow.extractions.add(
                extraction(key, category=category, attributes=values, minutes=1)  # type: ignore[arg-type]
            )
        # superseded extraction of "1": must not be matched by the latest-only filters
        await uow.extractions.add(
            extraction("1", attributes={"gpu": "OLD", "ram_gb": 2}, minutes=0)
        )
        await uow.commit()


def pred(attribute: str, op: Comparison, value: object) -> AttributePredicate:
    return AttributePredicate(attribute, op, value)  # type: ignore[arg-type]


FILTERS: dict[str, OfferFilter] = {
    "all": OfferFilter(),
    "search": OfferFilter(search=S1),
    "other-search": OfferFilter(search=S2),
    "relevant": OfferFilter(search=S1, relevance=RelevanceFilter.RELEVANT),
    "not-irrelevant": OfferFilter(search=S1, relevance=RelevanceFilter.NOT_IRRELEVANT),
    "irrelevant": OfferFilter(search=S1, relevance=RelevanceFilter.IRRELEVANT),
    "status": OfferFilter(statuses=frozenset({OfferStatus.SOLD, OfferStatus.REMOVED})),
    "status+search": OfferFilter(search=S1, statuses=frozenset({OfferStatus.ACTIVE})),
    "category": OfferFilter(category=CategoryName("laptop")),
    "category+search": OfferFilter(search=S2, category=CategoryName("phone")),
    "unknown-category": OfferFilter(category=CategoryName("tv")),
    "attr-gte-int": OfferFilter(attributes=(pred("ram_gb", Comparison.GE, 16),)),
    "attr-decimal": OfferFilter(attributes=(pred("screen_in", Comparison.LT, Decimal("16")),)),
    "attr-decimal-vs-int": OfferFilter(attributes=(pred("screen_in", Comparison.EQ, 17),)),
    "attr-string-ci": OfferFilter(attributes=(pred("gpu", Comparison.EQ, "GTX 1650"),)),
    "attr-contains": OfferFilter(attributes=(pred("gpu", Comparison.CONTAINS, "gtx"),)),
    "attr-ne-skips-null": OfferFilter(attributes=(pred("gpu", Comparison.NE, "Radeon"),)),
    "attr-bool": OfferFilter(attributes=(pred("new", Comparison.EQ, True),)),
    "attr-mixed-type": OfferFilter(attributes=(pred("ram_gb", Comparison.EQ, "16"),)),
    "attr-and": OfferFilter(
        search=S1,
        attributes=(pred("ram_gb", Comparison.GE, 16), pred("gpu", Comparison.CONTAINS, "rtx")),
    ),
    "attr-list-has": OfferFilter(attributes=(pred("damage", Comparison.CONTAINS, "screen"),)),
    "attr-list-lacks": OfferFilter(
        attributes=(pred("damage", Comparison.NOT_CONTAINS, "motherboard"),)
    ),
    "attr-not-in-latest": OfferFilter(attributes=(pred("gpu", Comparison.EQ, "OLD"),)),
    "everything": OfferFilter(
        search=S1,
        relevance=RelevanceFilter.NOT_IRRELEVANT,
        statuses=frozenset({OfferStatus.ACTIVE}),
        category=CategoryName("laptop"),
        attributes=(pred("ram_gb", Comparison.GE, 8),),
    ),
    "page-1": OfferFilter(limit=3),
    "page-2": OfferFilter(limit=3, offset=3),
    "page-past-end": OfferFilter(offset=50),
    "search-page": OfferFilter(search=S1, limit=2, offset=1),
    "attr-page": OfferFilter(attributes=(pred("ram_gb", Comparison.GE, 8),), limit=2, offset=1),
    "attr-search-page": OfferFilter(
        search=S1, attributes=(pred("ram_gb", Comparison.GE, 8),), limit=2, offset=2
    ),
}


def summary(items: list[OfferListItem]) -> list[tuple[object, ...]]:
    return [
        (
            str(i.offer.id),
            i.offer.last_seen_at,
            i.offer.status,
            None if i.link is None else (i.link.search, i.link.is_relevant, i.link.last_seen_at),
            None
            if i.extraction is None
            else (i.extraction.category, dict(i.extraction.attributes)),
        )
        for i in items
    ]


@pytest.fixture
async def both(store: SqlStore) -> tuple[InMemoryOfferQueries, SqlOfferQueries]:
    memory = InMemoryStore()
    await populate(memory.uow)
    await populate(store.uow)
    return InMemoryOfferQueries(memory), SqlOfferQueries(store.engine)


@pytest.mark.parametrize("name", list(FILTERS))
async def test_matches_the_in_memory_reference(
    both: tuple[InMemoryOfferQueries, SqlOfferQueries], name: str
) -> None:
    reference, sql = both
    expected = await reference.list_offers(FILTERS[name])
    actual = await sql.list_offers(FILTERS[name])
    assert summary(actual) == summary(expected)


async def test_reference_filters_are_not_vacuous(
    both: tuple[InMemoryOfferQueries, SqlOfferQueries],
) -> None:
    _, sql = both
    everything = await sql.list_offers(OfferFilter())
    assert [str(i.offer.id) for i in everything] == [
        "olx_pl:6",
        "olx_pl:10",
        "olx_pl:2",
        "olx_pl:3",
        "olx_pl:4",
        "olx_pl:1",
        "olx_pl:5",
        "olx_pl:7",
    ]
    assert (
        len(await sql.list_offers(OfferFilter(search=S1, relevance=RelevanceFilter.RELEVANT))) == 3
    )
    latest_only = await sql.list_offers(
        OfferFilter(attributes=(pred("gpu", Comparison.EQ, "OLD"),))
    )
    assert latest_only == []
    item = next(i for i in everything if str(i.offer.id) == "olx_pl:1")
    assert item.extraction is not None and item.extraction.attributes["gpu"] == "GTX 1650"
    assert item.link is None


async def test_list_attributes_round_trip_and_filter_in_sql(
    both: tuple[InMemoryOfferQueries, SqlOfferQueries],
) -> None:
    _, sql = both

    def ids(items: list[OfferListItem]) -> set[str]:
        return {str(i.offer.id) for i in items}

    has = await sql.list_offers(
        OfferFilter(attributes=(pred("damage", Comparison.CONTAINS, "screen"),))
    )
    assert ids(has) == {"olx_pl:3", "olx_pl:4"}
    stored = next(i for i in has if str(i.offer.id) == "olx_pl:4")
    assert stored.extraction is not None
    assert stored.extraction.attributes["damage"] == ("screen", "motherboard")
    lacks = await sql.list_offers(
        OfferFilter(attributes=(pred("damage", Comparison.NOT_CONTAINS, "motherboard"),))
    )
    assert ids(lacks) == {"olx_pl:3"}  # null damage never matches, 4 has motherboard

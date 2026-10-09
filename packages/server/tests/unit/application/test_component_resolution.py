"""ResolveComponents / ComponentResolutionStatus / AddComponentAlias over the in-memory store.

The same scenarios run against SQLite in
``tests/integration/persistence/test_component_resolution_sql.py``.
"""

from __future__ import annotations

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.use_cases.component_resolution import (
    AddComponentAlias,
    ComponentResolutionStatus,
    ResolveComponents,
)
from scrappy.domain.category import CategoryName
from scrappy.domain.component import (
    RESOLVER_VERSION,
    Component,
    ComponentAlias,
    ComponentKind,
    ResolutionMethod,
)
from scrappy.domain.extraction import ExtractionProvenance, OfferExtraction
from scrappy.domain.offer import ContentHash
from tests.unit.builders import at, oid
from tests.unit.fakes import FakeClock, InMemoryStore

GPU = ComponentKind.GPU
CPU = ComponentKind.CPU
HASH = ContentHash("ab" * 32)


def extraction(
    key: str,
    attributes: dict[str, object],
    *,
    category: str = "laptop",
    minutes: int = 0,
) -> OfferExtraction:
    return OfferExtraction(
        offer_id=oid(key),
        category=CategoryName(category),
        attributes=attributes,  # pyright: ignore[reportArgumentType]
        provenance=ExtractionProvenance(
            "m", "p1", None if category == "other" else 1, HASH, at(minutes)
        ),
    )


async def seed_components(store: InMemoryStore) -> None:
    names = [
        (GPU, "NVIDIA GeForce RTX 4060"),
        (GPU, "NVIDIA GeForce RTX 4060 Laptop GPU"),
        (GPU, "NVIDIA GeForce RTX 3050 Laptop GPU"),
        (GPU, "NVIDIA GeForce RTX 3050 6GB Laptop GPU"),
        (CPU, "12th Gen Intel(R) Core(TM) i5-12450H"),
    ]
    components = [Component.from_name(kind, name) for kind, name in names]
    async with store.uow() as uow:
        await uow.components.add_missing(components)
        await uow.components.add_aliases([ComponentAlias.for_name(c, c.name) for c in components])
        await uow.commit()


async def add_extractions(store: InMemoryStore, *items: OfferExtraction) -> None:
    async with store.uow() as uow:
        for item in items:
            await uow.extractions.add(item)
        await uow.commit()


def links(store: InMemoryStore) -> dict[tuple[str, str], tuple[str | None, str]]:
    return {
        (offer_id.external_id, kind.value): (
            link.resolution.component_id,
            link.resolution.method.value,
        )
        for (offer_id, kind), link in store.state.offer_components.items()
    }


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def resolver(store: InMemoryStore, clock: FakeClock, **kwargs: int) -> ResolveComponents:
    return ResolveComponents(uow=store.uow, clock=clock, **kwargs)


async def test_laptop_gpu_gets_the_laptop_variant_and_vram_picks_the_size(
    store: InMemoryStore, clock: FakeClock
) -> None:
    await seed_components(store)
    await add_extractions(
        store,
        extraction("a", {"gpu": "RTX 4060", "cpu": "i5 12450H"}),
        extraction("b", {"gpu": "RTX 3050", "vram_gb": 6}),
        extraction("c", {"gpu": "RTX 3050"}),
        extraction("d", {"gpu": "RTX 4060"}, category="pc"),
        extraction("e", {"gpu": "i7", "cpu": "brak"}),
        extraction("f", {"gpu": None, "cpu": "  "}),
        extraction("g", {}, category="other"),
    )

    report = await resolver(store, clock)()

    assert (report.processed, report.remaining) == (7, 0)
    assert report.by_method == {"exact": 5, "unresolved": 2}
    assert links(store) == {
        ("a", "gpu"): ("gpu:rtx-4060-laptop", "exact"),
        ("a", "cpu"): ("cpu:i5-12450h", "exact"),
        ("b", "gpu"): ("gpu:rtx-3050-6gb-laptop", "exact"),
        ("c", "gpu"): ("gpu:rtx-3050-laptop", "exact"),
        ("d", "gpu"): ("gpu:rtx-4060", "exact"),  # not a laptop category
        ("e", "gpu"): (None, "unresolved"),
        ("e", "cpu"): (None, "unresolved"),
    }


async def test_the_backlog_is_a_query_nothing_is_redone_until_text_or_version_changes(
    store: InMemoryStore, clock: FakeClock
) -> None:
    await seed_components(store)
    await add_extractions(store, extraction("a", {"gpu": "RTX 4060"}))
    assert (await resolver(store, clock)()).processed == 1
    assert (await resolver(store, clock)()).processed == 0  # up to date

    # the offer is re-extracted with another text: only that link is redone
    await add_extractions(store, extraction("a", {"gpu": "RTX 3050"}, minutes=5))
    again = await resolver(store, clock)()
    assert again.processed == 1
    assert (links(store))[("a", "gpu")][0] == "gpu:rtx-3050-laptop"

    # a new resolver version re-resolves everything without a new extraction
    bumped = await resolver(store, clock, resolver_version=RESOLVER_VERSION + 1)()
    assert bumped.processed == 1
    assert (await resolver(store, clock, resolver_version=RESOLVER_VERSION + 1)()).processed == 0


async def test_limit_and_chunks(store: InMemoryStore, clock: FakeClock) -> None:
    await seed_components(store)
    await add_extractions(store, *(extraction(str(i), {"gpu": "RTX 4060"}) for i in range(5)))

    first = await resolver(store, clock, chunk=2)(limit=3)
    assert (first.processed, first.remaining) == (3, 2)
    rest = await resolver(store, clock, chunk=2)()
    assert (rest.processed, rest.remaining) == (2, 0)


async def test_status_counts_and_top_unresolved_texts(
    store: InMemoryStore, clock: FakeClock
) -> None:
    await seed_components(store)
    await add_extractions(
        store,
        extraction("a", {"gpu": "RTX 4060"}),
        extraction("b", {"gpu": "Iris Xe"}),
        extraction("c", {"gpu": "iris xe"}),
        extraction("d", {"gpu": "integrated"}),
    )
    status = ComponentResolutionStatus(uow=store.uow)
    assert (await status()).backlog == 4

    await resolver(store, clock)()
    report = await status()

    assert report.backlog == 0
    assert report.counts == {"gpu": {"exact": 1, "unresolved": 3}}
    assert [(u.raw_text, u.offers) for u in report.top_unresolved] == [
        ("iris xe", 2),
        ("integrated", 1),
    ]


async def test_alias_add_makes_the_next_resolve_redo_only_the_covered_offers(
    store: InMemoryStore, clock: FakeClock
) -> None:
    await seed_components(store)
    await add_extractions(
        store,
        extraction("a", {"gpu": "Iris Xe"}),
        extraction("b", {"gpu": "iris  xe"}),
        extraction("c", {"gpu": "integrated"}),
    )
    await resolver(store, clock)()

    added = await AddComponentAlias(uow=store.uow)(GPU, "Iris Xe", "gpu:rtx-4060")
    assert (added.alias, added.links_marked_stale) == ("iris xe", 2)

    report = await resolver(store, clock)()
    assert (report.processed, report.by_method) == (2, {"alias": 2})
    assert links(store) == {
        ("a", "gpu"): ("gpu:rtx-4060", "alias"),
        ("b", "gpu"): ("gpu:rtx-4060", "alias"),
        ("c", "gpu"): (None, "unresolved"),
    }


async def test_alias_add_validates_the_target(store: InMemoryStore) -> None:
    await seed_components(store)
    add = AddComponentAlias(uow=store.uow)
    with pytest.raises(InvalidRequestError, match="unknown component"):
        await add(GPU, "iris xe", "gpu:nope")
    with pytest.raises(InvalidRequestError, match="is a cpu, not a gpu"):
        await add(GPU, "iris xe", "cpu:i5-12450h")
    with pytest.raises(InvalidRequestError, match="empty"):
        await add(GPU, "  ", "gpu:rtx-4060")


def test_method_values_are_the_documented_ones() -> None:
    assert {m.value for m in ResolutionMethod} == {"exact", "alias", "fuzzy", "llm", "unresolved"}

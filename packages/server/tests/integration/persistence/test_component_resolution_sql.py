"""The resolution backlog query, link storage and the use cases on real SQLite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from sqlalchemy import text

from scrappy.application.ports.components import ResolutionTask
from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.application.use_cases.component_resolution import (
    AddComponentAlias,
    ComponentResolutionStatus,
    ResolveComponents,
)
from scrappy.domain.category import CategoryName
from scrappy.domain.component import (
    Component,
    ComponentAlias,
    ComponentKind,
    OfferComponentLink,
    Resolution,
    ResolutionMethod,
)
from scrappy.domain.extraction import ExtractionProvenance, OfferExtraction
from tests.integration.persistence.sqlstore import SqlStore
from tests.integration.persistence.test_repositories import HASH, extraction, full_offer, seed
from tests.unit.builders import at, oid
from tests.unit.fakes import FakeClock

GPU = ComponentKind.GPU
CPU = ComponentKind.CPU
Factory = Callable[[], UnitOfWork]


async def seed_world(uow: Factory) -> None:
    await seed(uow, *(full_offer(str(i)) for i in range(1, 6)))
    async with uow() as u:
        await u.components.add_missing(
            [
                Component.from_name(GPU, "NVIDIA GeForce RTX 4060"),
                Component.from_name(GPU, "NVIDIA GeForce RTX 4060 Laptop GPU"),
                Component.from_name(CPU, "12th Gen Intel(R) Core(TM) i5-12450H"),
            ]
        )
        await u.extractions.add(extraction("1", attributes={"gpu": "RTX 4060", "vram_gb": 8}))
        await u.extractions.add(extraction("2", attributes={"cpu": "i5 12450H", "gpu": None}))
        other = OfferExtraction(
            oid("3"),
            CategoryName("other"),
            {},
            ExtractionProvenance("m", "p1", None, HASH, at(0)),
        )
        await u.extractions.add(other)
        await u.extractions.add(extraction("4", attributes={"gpu": "   ", "ram_gb": 16}))
        # only the LATEST extraction of an offer counts
        await u.extractions.add(extraction("5", attributes={"gpu": "GTX 1050"}, minutes=1))
        await u.extractions.add(extraction("5", attributes={"gpu": "GTX 1650"}, minutes=2))
        await u.commit()


def link(key: str, kind: ComponentKind, raw: str, version: int) -> OfferComponentLink:
    return OfferComponentLink(oid(key), kind, raw, Resolution.unresolved(), version, at(10))


async def test_backlog_is_the_current_extractions_without_an_up_to_date_link(
    uow: Factory,
) -> None:
    await seed_world(uow)
    async with uow() as u:
        backlog = await u.components.resolution_backlog(1)
        assert {(t.offer_id.external_id, t.kind, t.raw_text) for t in backlog} == {
            ("1", GPU, "RTX 4060"),
            ("2", CPU, "i5 12450H"),
            ("5", GPU, "GTX 1650"),
        }
        first = next(t for t in backlog if t.offer_id.external_id == "1")
        assert first == ResolutionTask(oid("1"), "laptop", GPU, "RTX 4060", 8)
        assert await u.components.count_resolution_backlog(1) == 3
        assert len(await u.components.resolution_backlog(1, limit=2)) == 2

        await u.components.save_links(
            [link("1", GPU, "RTX 4060", 1), link("2", CPU, "i5 12450H", 1)]
        )
        await u.commit()

    async with uow() as u:
        # up to date: only offer 5 is left
        assert [t.offer_id.external_id for t in await u.components.resolution_backlog(1)] == ["5"]
        # a bumped resolver version makes every link stale
        assert await u.components.count_resolution_backlog(2) == 3
        # a changed raw text makes just that link stale
        await u.extractions.add(extraction("1", attributes={"gpu": "RTX 3050"}, minutes=9))
        tasks = await u.components.resolution_backlog(1)
        assert {(t.offer_id.external_id, t.raw_text) for t in tasks} == {
            ("1", "RTX 3050"),
            ("5", "GTX 1650"),
        }
        await u.commit()


async def test_links_are_upserted_counted_and_marked_stale(uow: Factory, store: SqlStore) -> None:
    await seed_world(uow)
    exact = replace(
        link("1", GPU, "RTX 4060", 1),
        resolution=Resolution("gpu:rtx-4060-laptop", 0.95, ResolutionMethod.EXACT),
    )
    async with uow() as u:
        await u.components.save_links(
            [exact, link("2", CPU, "I5", 1), link("5", GPU, "Gtx", 1), link("4", GPU, "gtx", 1)]
        )
        await u.components.save_links([replace(exact, raw_text="RTX 4060 8GB")])  # upsert
        await u.commit()

    async with uow() as u:
        assert await u.components.link_counts() == {
            (GPU, ResolutionMethod.EXACT): 1,
            (GPU, ResolutionMethod.UNRESOLVED): 2,
            (CPU, ResolutionMethod.UNRESOLVED): 1,
        }
        top = await u.components.top_unresolved(5)
        assert [(t.kind, t.raw_text, t.offers) for t in top] == [
            (GPU, "gtx", 2),
            (CPU, "i5", 1),
        ]
        assert sorted(await u.components.linked_raw_texts(GPU)) == ["Gtx", "RTX 4060 8GB", "gtx"]
        assert await u.components.mark_links_stale(GPU, ["Gtx", "gtx"]) == 2
        assert await u.components.mark_links_stale(GPU, []) == 0
        await u.commit()

    async with store.engine.connect() as conn:
        versions = (
            await conn.execute(text("select raw_text, resolver_version from offer_components"))
        ).all()
    assert sorted(versions) == [("Gtx", 0), ("I5", 1), ("RTX 4060 8GB", 1), ("gtx", 0)]


async def test_alias_flow_end_to_end(uow: Factory) -> None:
    await seed_world(uow)
    clock = FakeClock()
    resolve = ResolveComponents(uow=uow, clock=clock, chunk=2)

    report = await resolve()
    assert (report.processed, report.remaining) == (3, 0)
    assert report.by_method == {"exact": 2, "unresolved": 1}  # GTX 1650 is not in the catalog

    status = await ComponentResolutionStatus(uow=uow)()
    assert status.counts == {"gpu": {"exact": 1, "unresolved": 1}, "cpu": {"exact": 1}}
    assert [(t.raw_text, t.offers) for t in status.top_unresolved] == [("gtx 1650", 1)]

    added = await AddComponentAlias(uow=uow)(GPU, "GTX 1650", "gpu:rtx-4060")
    assert added.links_marked_stale == 1
    again = await resolve()
    assert (again.processed, again.by_method) == (1, {"alias": 1})
    assert (await ComponentResolutionStatus(uow=uow)()).top_unresolved == []

    async with uow() as u:
        assert await u.components.list_aliases() == [
            ComponentAlias(GPU, "gtx 1650", "gpu:rtx-4060")
        ]
        assert len(await u.components.list_components()) == 3

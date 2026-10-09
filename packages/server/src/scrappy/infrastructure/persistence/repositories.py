"""SQL implementations of the repository ports (SQLAlchemy Core, async).

Every repository wraps the unit of work's single :class:`AsyncConnection`, so all of them
(and the job queue) share one transaction. Returned domain objects are always freshly built
from rows: they never write through.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection

from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import Offer, OfferId, OfferSnapshot
from scrappy.domain.run import RunStatus, ScrapeRun
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import RunId
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence._sql import chunks, upsert
from scrappy.infrastructure.persistence.tables import (
    extractions,
    offer_snapshots,
    offers,
    saved_searches,
    scrape_runs,
    search_offers,
)


def _key(offer_id: OfferId) -> tuple[str, str]:
    return (offer_id.source.value, offer_id.external_id)


def _unique_keys(offer_ids: Collection[OfferId]) -> list[tuple[str, str]]:
    return sorted({_key(i) for i in offer_ids})


class SqlOfferRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, offer_id: OfferId) -> Offer | None:
        stmt = select(offers).where(
            offers.c.source == offer_id.source.value, offers.c.external_id == offer_id.external_id
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.offer_from(row, offers.c)

    async def get_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, Offer]:
        result: dict[OfferId, Offer] = {}
        for part in chunks(_unique_keys(offer_ids)):
            stmt = select(offers).where(tuple_(offers.c.source, offers.c.external_id).in_(part))
            for row in (await self._conn.execute(stmt)).mappings():
                offer = m.offer_from(row, offers.c)
                result[offer.id] = offer
        return result

    async def save(self, offer: Offer) -> None:
        await upsert(self._conn, offers, m.offer_values(offer), ["source", "external_id"])

    async def add_snapshot(self, snapshot: OfferSnapshot) -> None:
        await self._conn.execute(offer_snapshots.insert().values(m.snapshot_values(snapshot)))

    async def list_snapshots(self, offer_id: OfferId) -> list[OfferSnapshot]:
        stmt = (
            select(offer_snapshots)
            .where(
                offer_snapshots.c.source == offer_id.source.value,
                offer_snapshots.c.external_id == offer_id.external_id,
            )
            # "oldest first" = insertion order (the fake keeps a list)
            .order_by(offer_snapshots.c.seq)
        )
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.snapshot_from(row, offer_snapshots.c) for row in rows]

    async def list_with_content(self, *, after: OfferId | None, limit: int) -> list[Offer]:
        stmt = select(offers).where(offers.c.content_hash.is_not(None))
        if after is not None:
            stmt = stmt.where(tuple_(offers.c.source, offers.c.external_id) > tuple_(*_key(after)))
        # BINARY / "C" collation order == Python's str ordering for the (ASCII) ids.
        stmt = stmt.order_by(offers.c.source, offers.c.external_id).limit(limit)
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.offer_from(row, offers.c) for row in rows]


class SqlSavedSearchRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, name: SearchName) -> SavedSearch | None:
        stmt = select(saved_searches).where(saved_searches.c.name == name.value)
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.search_from(row, saved_searches.c)

    async def save(self, search: SavedSearch) -> None:
        await upsert(self._conn, saved_searches, m.search_values(search), ["name"])

    async def list_all(self) -> list[SavedSearch]:
        stmt = select(saved_searches).order_by(saved_searches.c.name)
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.search_from(row, saved_searches.c) for row in rows]


class SqlSearchOfferRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, search: SearchName, offer_id: OfferId) -> SearchOffer | None:
        stmt = select(search_offers).where(
            search_offers.c.search == search.value,
            search_offers.c.source == offer_id.source.value,
            search_offers.c.external_id == offer_id.external_id,
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.link_from(row, search_offers.c)

    async def get_many(
        self, search: SearchName, offer_ids: Collection[OfferId]
    ) -> dict[OfferId, SearchOffer]:
        result: dict[OfferId, SearchOffer] = {}
        for part in chunks(_unique_keys(offer_ids)):
            stmt = select(search_offers).where(
                search_offers.c.search == search.value,
                tuple_(search_offers.c.source, search_offers.c.external_id).in_(part),
            )
            for row in (await self._conn.execute(stmt)).mappings():
                link = m.link_from(row, search_offers.c)
                result[link.offer_id] = link
        return result

    async def save(self, link: SearchOffer) -> None:
        await upsert(
            self._conn, search_offers, m.link_values(link), ["search", "source", "external_id"]
        )

    async def list_for_offer(self, offer_id: OfferId) -> list[SearchOffer]:
        stmt = (
            select(search_offers)
            .where(
                search_offers.c.source == offer_id.source.value,
                search_offers.c.external_id == offer_id.external_id,
            )
            .order_by(search_offers.c.search)
        )
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.link_from(row, search_offers.c) for row in rows]


def latest_extraction_cte(ids: Sequence[tuple[str, str]] | None = None) -> Any:
    """Rows of the latest extraction per offer: newest ``extracted_at``, then last inserted."""
    rank = (
        func.row_number()
        .over(
            partition_by=[extractions.c.source, extractions.c.external_id],
            order_by=[extractions.c.extracted_at.desc(), extractions.c.seq.desc()],
        )
        .label("rn")
    )
    stmt: Select[Any] = select(extractions, rank)
    if ids is not None:
        stmt = stmt.where(tuple_(extractions.c.source, extractions.c.external_id).in_(ids))
    ranked = stmt.subquery("ranked")
    return select(ranked).where(ranked.c.rn == 1).subquery("latest")


class SqlExtractionRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def add(self, extraction: OfferExtraction) -> None:
        await self._conn.execute(extractions.insert().values(m.extraction_values(extraction)))

    async def latest(self, offer_id: OfferId) -> OfferExtraction | None:
        return (await self.latest_many([offer_id])).get(offer_id)

    async def latest_many(self, offer_ids: Collection[OfferId]) -> dict[OfferId, OfferExtraction]:
        result: dict[OfferId, OfferExtraction] = {}
        for part in chunks(_unique_keys(offer_ids)):
            latest = latest_extraction_cte(part)
            for row in (await self._conn.execute(select(latest))).mappings():
                extraction = m.extraction_from(row, latest.c)
                result[extraction.offer_id] = extraction
        return result


class SqlScrapeRunRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, run_id: RunId) -> ScrapeRun | None:
        stmt = select(scrape_runs).where(scrape_runs.c.id == run_id.value)
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.run_from(row, scrape_runs.c)

    async def save(self, run: ScrapeRun) -> None:
        # conflict on the public id; ``seq`` (insertion order) is kept on update
        await upsert(self._conn, scrape_runs, m.run_values(run), ["id"])

    async def find_running(self, search: SearchName) -> ScrapeRun | None:
        stmt = (
            select(scrape_runs)
            .where(
                scrape_runs.c.search == search.value,
                scrape_runs.c.status == RunStatus.RUNNING.value,
            )
            .order_by(scrape_runs.c.seq)
            .limit(1)
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return None if row is None else m.run_from(row, scrape_runs.c)

    async def list_for_search(self, search: SearchName, *, limit: int) -> list[ScrapeRun]:
        stmt = (
            select(scrape_runs)
            .where(scrape_runs.c.search == search.value)
            # ties keep insertion order, like the fake's stable sort
            .order_by(scrape_runs.c.started_at.desc(), scrape_runs.c.seq)
            .limit(limit)
        )
        rows = (await self._conn.execute(stmt)).mappings()
        return [m.run_from(row, scrape_runs.c) for row in rows]


__all__ = [
    "SqlExtractionRepository",
    "SqlOfferRepository",
    "SqlSavedSearchRepository",
    "SqlScrapeRunRepository",
    "SqlSearchOfferRepository",
    "latest_extraction_cte",
]

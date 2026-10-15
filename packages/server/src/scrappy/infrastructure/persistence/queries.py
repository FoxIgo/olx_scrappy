"""``SqlOfferQueries``: the read side (``OfferQueries`` port) over committed data.

Semantics are those of :func:`scrappy.application.ports.queries.matches_filter`:

* search / status / relevance (``coalesce(override, derived)``) / category (latest
  extraction) are filtered **in SQL**, ordered by ``last_seen_at`` desc (the link's when a
  search is given, else the offer's) then ``source:external_id``, and paged in SQL.
* **Attribute predicates are applied in Python** with the domain's own
  ``AttributePredicate.matches`` (the specification), over the SQL-filtered, ordered rows;
  paging is then applied after them (rows are streamed, so a ``limit`` stops early).

Trade-off: correct by construction and portable (SQLite and PostgreSQL), at the cost of
reading every SQL-matching row's attributes when attribute predicates are used. With tens
of thousands of offers filtered by search/category first this is cheap. When it is not, a
JSON-path predicate translation (SQLite ``json_extract`` / PostgreSQL JSONB ``->>``) can
narrow the SQL part without changing the Python check, which stays the arbiter.

Reads use their own connection in a plain deferred transaction (WAL snapshot), so they
never block the writer and are not part of a unit of work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from scrappy.application.ports.queries import (
    LivenessFilter,
    OfferFilter,
    OfferListItem,
    RelevanceFilter,
    matches_filter,
)
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence.engine import READ_ONLY_OPTION
from scrappy.infrastructure.persistence.repositories import latest_extraction_cte
from scrappy.infrastructure.persistence.tables import offers, search_offers


class SqlOfferQueries:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_offers(self, query: OfferFilter) -> list[OfferListItem]:
        latest = latest_extraction_cte()
        stmt = self._statement(query, latest)
        python_filtering = bool(query.attributes) or query.liveness is not LivenessFilter.ALL
        if not python_filtering:
            stmt = stmt.limit(query.limit).offset(query.offset)

        items: list[OfferListItem] = []
        skipped = 0
        async with self._engine.connect() as conn:
            await conn.execution_options(**{READ_ONLY_OPTION: True})
            result = await conn.stream(stmt)
            try:
                async for row in result.mappings():
                    item = self._item(row, latest, query)
                    if python_filtering:
                        if not matches_filter(item, query):
                            continue
                        if skipped < query.offset:
                            skipped += 1
                            continue
                    items.append(item)
                    if len(items) >= query.limit:
                        break
            finally:
                await result.close()
        return items

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _statement(query: OfferFilter, latest: Any) -> Any:
        columns: list[Any] = [offers, latest]
        source = offers.outerjoin(
            latest,
            (latest.c.source == offers.c.source) & (latest.c.external_id == offers.c.external_id),
        )
        conditions: list[ColumnElement[bool]] = []
        if query.search is not None:
            columns.insert(1, search_offers)
            source = source.join(
                search_offers,
                (search_offers.c.source == offers.c.source)
                & (search_offers.c.external_id == offers.c.external_id)
                & (search_offers.c.search == query.search.value),
            )
            effective = func.coalesce(
                search_offers.c.relevance_override, search_offers.c.derived_relevance
            )
            match query.relevance:
                case RelevanceFilter.ALL:
                    pass
                case RelevanceFilter.RELEVANT:
                    conditions.append(effective.is_(True))
                case RelevanceFilter.NOT_IRRELEVANT:
                    conditions.append(effective.is_not(False))
                case RelevanceFilter.IRRELEVANT:
                    conditions.append(effective.is_(False))
            seen = search_offers.c.last_seen_at
        else:
            seen = offers.c.last_seen_at
        if query.statuses:
            conditions.append(offers.c.status.in_(sorted(s.value for s in query.statuses)))
        if query.has_delivery is not None:
            conditions.append(offers.c.has_delivery.is_(query.has_delivery))
        if query.category is not None:
            conditions.append(latest.c.category == query.category.value)
        stmt = select(*columns).select_from(source).where(*conditions)
        return stmt.order_by(seen.desc(), offers.c.source + ":" + offers.c.external_id)

    @staticmethod
    def _item(row: m.Row, latest: Any, query: OfferFilter) -> OfferListItem:
        offer = m.offer_from(row, offers.c)
        link = m.link_from(row, search_offers.c) if query.search is not None else None
        extraction = None
        if row[latest.c.category] is not None:
            extraction = m.extraction_from(row, latest.c)
        return OfferListItem(offer, link, extraction)

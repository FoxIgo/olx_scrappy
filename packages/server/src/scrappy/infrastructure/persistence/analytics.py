"""``SqlAnalyticsQueries``: the ``AnalyticsQueries`` read side over committed data (ADR 0009).

SQL does the filtering that is portable and selective: search membership, status, effective
relevance (``coalesce(override, derived)``), category, and the "latest extraction per offer"
join (the same ``row_number`` CTE the repositories use). Attribute predicates are NOT
translated: the use cases apply them in Python with ``AttributePredicate`` (the specification),
the same trade-off as :mod:`scrappy.infrastructure.persistence.queries`.

JSON attribute access (needed only for null-rate counting) is dialect-specific and lives in
:func:`scrappy.infrastructure.persistence._sql.json_attribute`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Connection, exists, func, inspect, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import (
    AttributeFill,
    ColumnInfo,
    ExtractionCoverage,
    OfferRow,
    OfferScope,
    OverviewRows,
    SearchCounts,
    SqlResult,
    TableInfo,
)
from scrappy.application.ports.scoring import ComponentFact
from scrappy.domain.category import CategoryName
from scrappy.domain.component import ComponentKind, ResolutionMethod
from scrappy.domain.offer import OfferId, OfferSnapshot, OfferStatus, PriceKind
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SearchName, SearchOffer
from scrappy.infrastructure.persistence import mapping as m
from scrappy.infrastructure.persistence._sql import CHUNK, chunks, json_attribute
from scrappy.infrastructure.persistence.engine import READ_ONLY_OPTION
from scrappy.infrastructure.persistence.readonly_sql import (
    run_sqlite_read_only,
    validate_read_only_sql,
)
from scrappy.infrastructure.persistence.repositories import latest_extraction_cte
from scrappy.infrastructure.persistence.tables import (
    component_benchmarks,
    components,
    offer_components,
    offer_snapshots,
    offers,
    saved_searches,
    scrape_runs,
    search_offers,
)

HIDDEN_TABLES = frozenset({"alembic_version"})


def _effective() -> ColumnElement[Any]:
    return func.coalesce(search_offers.c.relevance_override, search_offers.c.derived_relevance)


class SqlAnalyticsQueries:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name

    # ----------------------------------------------------------------------- offers
    async def offer_rows(self, scope: OfferScope) -> list[OfferRow]:
        latest = latest_extraction_cte()
        columns: list[Any] = [offers, latest.c.category, latest.c.attributes, latest.c.extracted_at]
        if scope.search is not None:
            columns.append(search_offers)
        stmt = self._base(select(*columns), scope, latest)
        async with self._read() as conn:
            result = (await conn.execute(stmt)).mappings().all()
            links: dict[OfferId, list[SearchOffer]] = defaultdict(list)
            if scope.search is None and result:
                keys = [(r[offers.c.source], r[offers.c.external_id]) for r in result]
                for part in chunks(keys, CHUNK):
                    link_stmt = select(search_offers).where(
                        tuple_(search_offers.c.source, search_offers.c.external_id).in_(part)
                    )
                    for row in (await conn.execute(link_stmt)).mappings():
                        link = m.link_from(row, search_offers.c)
                        links[link.offer_id].append(link)
        rows: list[OfferRow] = []
        for row in result:
            offer_id = m.offer_id_of(row, offers.c)
            category = row[latest.c.category]
            amount = row[offers.c.price_amount]
            kind = row[offers.c.price_kind]
            rows.append(
                OfferRow(
                    offer_id=offer_id,
                    url=row[offers.c.url],
                    title=row[offers.c.title],
                    location=row[offers.c.location],
                    status=OfferStatus(row[offers.c.status]),
                    price_kind=None if kind is None else PriceKind(kind),
                    price_amount=None if amount is None else Decimal(amount),
                    price_currency=row[offers.c.price_currency],
                    price_negotiable=row[offers.c.price_negotiable],
                    first_seen_at=row[offers.c.first_seen_at],
                    last_seen_at=row[offers.c.last_seen_at],
                    category=None if category is None else CategoryName(category),
                    attributes={}
                    if category is None
                    else m.attributes_from_json(row[latest.c.attributes]),
                    extracted_at=row[latest.c.extracted_at],
                    links=(m.link_from(row, search_offers.c),)
                    if scope.search is not None
                    else tuple(links.get(offer_id, ())),
                )
            )
        return rows

    async def count_offers(self, scope: OfferScope) -> int:
        latest = latest_extraction_cte()
        stmt = self._base(select(func.count()), scope, latest)
        async with self._read() as conn:
            return int((await conn.execute(stmt)).scalar_one())

    @staticmethod
    def _base(stmt: Any, scope: OfferScope, latest: Any) -> Any:
        source: Any = offers.outerjoin(
            latest,
            (latest.c.source == offers.c.source) & (latest.c.external_id == offers.c.external_id),
        )
        conditions: list[ColumnElement[bool]] = []
        if scope.search is not None:
            source = source.join(
                search_offers,
                (search_offers.c.source == offers.c.source)
                & (search_offers.c.external_id == offers.c.external_id)
                & (search_offers.c.search == scope.search.value),
            )
            if scope.relevant_only:
                conditions.append(_effective().is_(True))
        elif scope.relevant_only:
            conditions.append(
                exists().where(
                    (search_offers.c.source == offers.c.source)
                    & (search_offers.c.external_id == offers.c.external_id)
                    & _effective().is_(True)
                )
            )
        if scope.statuses:
            conditions.append(offers.c.status.in_(sorted(s.value for s in scope.statuses)))
        if scope.category is not None:
            conditions.append(latest.c.category == scope.category.value)
        return stmt.select_from(source).where(*conditions)

    # ------------------------------------------------------------------- scoring facts
    async def component_facts(self, offer_ids: Sequence[OfferId]) -> list[ComponentFact]:
        keys = [(o.source.value, o.external_id) for o in offer_ids]
        oc, b = offer_components.c, component_benchmarks.c
        facts: list[ComponentFact] = []
        async with self._read() as conn:
            for part in chunks(keys, CHUNK):
                stmt = (
                    select(
                        oc.source,
                        oc.external_id,
                        oc.kind,
                        oc.component_id,
                        oc.confidence,
                        oc.method,
                        components.c.name,
                        b.source.label("bench_source"),
                        b.metric,
                        b.score,
                        b.samples,
                    )
                    .select_from(
                        offer_components.join(components, components.c.id == oc.component_id).join(
                            component_benchmarks, b.component_id == oc.component_id
                        )
                    )
                    .where(tuple_(oc.source, oc.external_id).in_(part))
                )
                for row in (await conn.execute(stmt)).mappings():
                    facts.append(
                        ComponentFact(
                            offer_id=m.offer_id_of(row, oc),
                            kind=ComponentKind(row["kind"]),
                            component_id=row["component_id"],
                            component_name=row["name"],
                            source=row["bench_source"],
                            metric=row["metric"],
                            score=float(row["score"]),
                            samples=int(row["samples"]),
                            confidence=float(row["confidence"]),
                            method=ResolutionMethod(row["method"]),
                        )
                    )
        return facts

    async def component_offer_counts(self) -> dict[str, int]:
        oc = offer_components.c
        stmt = (
            select(oc.component_id, func.count())
            .where(oc.component_id.is_not(None))
            .group_by(oc.component_id)
        )
        async with self._read() as conn:
            return {str(cid): int(n) for cid, n in (await conn.execute(stmt)).all()}

    # ------------------------------------------------------------------- overview
    async def overview(self) -> OverviewRows:
        latest = latest_extraction_cte()
        effective = _effective()
        counts = (
            select(
                search_offers.c.search,
                func.count().label("total"),
                func.count().filter(effective.is_(True)).label("relevant"),
                func.count().filter(effective.is_(False)).label("irrelevant"),
                func.count().filter(effective.is_(None)).label("unknown"),
                func.count().filter(latest.c.category.is_not(None)).label("extracted"),
            )
            .select_from(
                search_offers.outerjoin(
                    latest,
                    (latest.c.source == search_offers.c.source)
                    & (latest.c.external_id == search_offers.c.external_id),
                )
            )
            .group_by(search_offers.c.search)
        )
        async with self._read() as conn:
            by_search = {r["search"]: r for r in (await conn.execute(counts)).mappings()}
            searches: list[SearchCounts] = []
            saved = (
                await conn.execute(select(saved_searches).order_by(saved_searches.c.name))
            ).mappings()
            for row in saved:
                search = m.search_from(row, saved_searches.c)
                c = by_search.get(search.name.value)
                searches.append(
                    SearchCounts(
                        search,
                        *(
                            (0, 0, 0, 0, 0)
                            if c is None
                            else (
                                c["total"],
                                c["relevant"],
                                c["irrelevant"],
                                c["unknown"],
                                c["extracted"],
                            )
                        ),
                    )
                )

            async def count(table_or_cte: Any) -> int:
                return int(
                    (
                        await conn.execute(select(func.count()).select_from(table_or_cte))
                    ).scalar_one()
                )

            return OverviewRows(
                dialect=self.dialect,
                searches=searches,
                offers_total=await count(offers),
                offers_extracted=await count(latest),
                snapshots_total=await count(offer_snapshots),
                runs_total=await count(scrape_runs),
            )

    # ----------------------------------------------------------------------- history
    async def snapshots(
        self, *, offer_ids: Sequence[OfferId] | None = None, since: datetime | None = None
    ) -> list[OfferSnapshot]:
        result: list[OfferSnapshot] = []
        parts: list[Sequence[tuple[str, str]] | None]
        if offer_ids is None:
            parts = [None]
        else:
            parts = list(chunks([(o.source.value, o.external_id) for o in offer_ids], CHUNK))
        async with self._read() as conn:
            for part in parts:
                stmt = select(offer_snapshots)
                if part is not None:
                    stmt = stmt.where(
                        tuple_(offer_snapshots.c.source, offer_snapshots.c.external_id).in_(part)
                    )
                if since is not None:
                    stmt = stmt.where(offer_snapshots.c.observed_at >= since)
                for row in (await conn.execute(stmt)).mappings():
                    result.append(m.snapshot_from(row, offer_snapshots.c))
        result.sort(key=lambda s: s.observed_at, reverse=True)
        return result

    async def recent_runs(self, search: SearchName | None, limit: int) -> list[ScrapeRun]:
        stmt = select(scrape_runs).order_by(scrape_runs.c.seq.desc()).limit(limit)
        if search is not None:
            stmt = stmt.where(scrape_runs.c.search == search.value)
        async with self._read() as conn:
            return [m.run_from(r, scrape_runs.c) for r in (await conn.execute(stmt)).mappings()]

    # ------------------------------------------------------------------------ health
    async def extraction_coverage(self, search: SearchName | None) -> ExtractionCoverage:
        latest = latest_extraction_cte()
        if search is None:
            source: Any = offers.outerjoin(
                latest,
                (latest.c.source == offers.c.source)
                & (latest.c.external_id == offers.c.external_id),
            )
        else:
            source = search_offers.outerjoin(
                latest,
                (latest.c.source == search_offers.c.source)
                & (latest.c.external_id == search_offers.c.external_id),
            )
        stmt = select(
            func.count(), func.count().filter(latest.c.category.is_not(None))
        ).select_from(source)
        if search is not None:
            stmt = stmt.where(search_offers.c.search == search.value)
        async with self._read() as conn:
            total, extracted = (await conn.execute(stmt)).one()
        return ExtractionCoverage(int(total), int(extracted))

    async def attribute_fill(
        self, category: CategoryName, attributes: Sequence[str], search: SearchName | None
    ) -> list[AttributeFill]:
        if not attributes:
            return []
        latest = latest_extraction_cte()
        dialect = self.dialect
        filled = [
            func.count(json_attribute(latest.c.attributes, name, dialect)).label(f"f{i}")
            for i, name in enumerate(attributes)
        ]
        stmt = select(func.count().label("total"), *filled).select_from(latest)
        stmt = stmt.where(latest.c.category == category.value)
        if search is not None:
            stmt = stmt.where(
                exists().where(
                    (search_offers.c.source == latest.c.source)
                    & (search_offers.c.external_id == latest.c.external_id)
                    & (search_offers.c.search == search.value)
                )
            )
        async with self._read() as conn:
            row = (await conn.execute(stmt)).mappings().one()
        return [
            AttributeFill(category, name, int(row["total"]), int(row[f"f{i}"]))
            for i, name in enumerate(attributes)
        ]

    # ------------------------------------------------------------------------ schema
    async def tables(self) -> list[TableInfo]:
        def reflect(conn: Connection) -> list[TableInfo]:
            inspector = inspect(conn)
            result: list[TableInfo] = []
            for name in sorted(inspector.get_table_names()):
                if name in HIDDEN_TABLES or name.startswith("sqlite_"):
                    continue
                pk = set(inspector.get_pk_constraint(name).get("constrained_columns") or ())
                columns = [
                    ColumnInfo(
                        c["name"], str(c["type"]), bool(c.get("nullable", True)), c["name"] in pk
                    )
                    for c in inspector.get_columns(name)
                ]
                result.append(TableInfo(name, columns))
            return result

        async with self._read() as conn:
            return await conn.run_sync(reflect)

    # --------------------------------------------------------------------- raw SQL
    async def execute_sql(self, sql: str, *, max_rows: int, timeout_seconds: float) -> SqlResult:
        statement = validate_read_only_sql(sql)
        return await self.execute_validated_sql(
            statement, max_rows=max_rows, timeout_seconds=timeout_seconds
        )

    async def execute_validated_sql(
        self, statement: str, *, max_rows: int, timeout_seconds: float
    ) -> SqlResult:
        """Run ``statement`` on a read-only connection WITHOUT validating it (the read-only
        connection is the safety net; tests use this to prove it holds on its own)."""
        if self.dialect == "sqlite":
            path = self._engine.url.database
            if not path or path == ":memory:":
                raise InvalidRequestError("q sql needs a file-based SQLite database")
            return await asyncio.to_thread(
                run_sqlite_read_only,
                path,
                statement,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        return await self._run_postgres(statement, max_rows, timeout_seconds)

    async def _run_postgres(self, statement: str, max_rows: int, seconds: float) -> SqlResult:
        # untested against a live server: a READ ONLY transaction plus statement_timeout
        async with self._engine.connect() as conn:
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(seconds * 1000)}")
            try:
                cursor = await conn.exec_driver_sql(statement)
                fetched = cursor.fetchmany(max_rows + 1)
            except Exception as error:
                raise InvalidRequestError(f"SQL error: {error}") from error
            columns = tuple(cursor.keys())
            await conn.rollback()
        return SqlResult(columns, [tuple(r) for r in fetched[:max_rows]], len(fetched) > max_rows)

    # --------------------------------------------------------------------- internals
    def _read(self) -> _Read:
        return _Read(self._engine)


class _Read:
    """Async context manager: a connection in a plain deferred (snapshot) transaction."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._conn: AsyncConnection | None = None

    async def __aenter__(self) -> AsyncConnection:
        self._conn = await self._engine.connect()
        await self._conn.execution_options(**{READ_ONLY_OPTION: True})
        return self._conn

    async def __aexit__(self, *_exc: object) -> None:
        if self._conn is not None:
            await self._conn.close()

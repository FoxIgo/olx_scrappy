"""In-memory ``AnalyticsQueries``: the reference behaviour for the SQL adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from scrappy.application.errors import InvalidRequestError
from scrappy.application.jobs.model import JobType
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
from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import OfferId, OfferSnapshot
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SearchName, SearchOffer
from tests.unit.fakes.store import InMemoryStore


class InMemoryAnalyticsQueries:
    def __init__(self, store: InMemoryStore, *, dialect: str = "sqlite") -> None:
        self._store = store
        self._dialect = dialect
        self.sql_calls: list[tuple[str, int, float]] = []
        self.sql_result = SqlResult(("x",), [(1,)], False)

    @property
    def dialect(self) -> str:
        return self._dialect

    def _latest(self) -> dict[OfferId, OfferExtraction]:
        latest: dict[OfferId, OfferExtraction] = {}
        for extraction in self._store.state.extractions:  # later insertion wins ties
            current = latest.get(extraction.offer_id)
            if current is None or extraction.provenance.extracted_at >= (
                current.provenance.extracted_at
            ):
                latest[extraction.offer_id] = extraction
        return latest

    def _links(self, offer_id: OfferId) -> list[SearchOffer]:
        return [link for (_, oid), link in self._store.state.links.items() if oid == offer_id]

    async def offer_rows(self, scope: OfferScope) -> list[OfferRow]:
        state = self._store.state
        latest = self._latest()
        rows: list[OfferRow] = []
        for offer_id, offer in state.offers.items():
            links = self._links(offer_id)
            if scope.search is not None:
                links = [link for link in links if link.search == scope.search]
                if not links:
                    continue
            if scope.relevant_only and not any(link.is_relevant is True for link in links):
                continue
            if scope.statuses and offer.status not in scope.statuses:
                continue
            extraction = latest.get(offer_id)
            if scope.category is not None and (
                extraction is None or extraction.category != scope.category
            ):
                continue
            price = offer.price
            rows.append(
                OfferRow(
                    offer_id=offer_id,
                    url=offer.url,
                    title=offer.title,
                    location=offer.location,
                    status=offer.status,
                    price_kind=None if price is None else price.kind,
                    price_amount=None
                    if price is None or price.amount is None
                    else price.amount.amount,
                    price_currency=None
                    if price is None or price.amount is None
                    else price.amount.currency,
                    price_negotiable=None if price is None else price.negotiable,
                    first_seen_at=offer.first_seen_at,
                    last_seen_at=offer.last_seen_at,
                    category=None if extraction is None else extraction.category,
                    attributes={} if extraction is None else dict(extraction.attributes),
                    extracted_at=None if extraction is None else extraction.provenance.extracted_at,
                    links=tuple(links),
                )
            )
        return rows

    async def count_offers(self, scope: OfferScope) -> int:
        return len(await self.offer_rows(scope))

    async def overview(self) -> OverviewRows:
        state = self._store.state
        latest = self._latest()
        searches: list[SearchCounts] = []
        for name in sorted(state.searches):
            links = [link for (s, _), link in state.links.items() if s == name]
            searches.append(
                SearchCounts(
                    state.searches[name],
                    offers=len(links),
                    relevant=sum(1 for lk in links if lk.is_relevant is True),
                    irrelevant=sum(1 for lk in links if lk.is_relevant is False),
                    unknown=sum(1 for lk in links if lk.is_relevant is None),
                    extracted=sum(1 for lk in links if lk.offer_id in latest),
                )
            )
        return OverviewRows(
            self._dialect,
            searches,
            len(state.offers),
            len(latest),
            len(state.snapshots),
            len(state.runs),
        )

    async def snapshots(
        self, *, offer_ids: Sequence[OfferId] | None = None, since: datetime | None = None
    ) -> list[OfferSnapshot]:
        found = [
            s
            for s in self._store.state.snapshots
            if (offer_ids is None or s.offer_id in offer_ids)
            and (since is None or s.observed_at >= since)
        ]
        return sorted(found, key=lambda s: s.observed_at, reverse=True)

    async def recent_runs(self, search: SearchName | None, limit: int) -> list[ScrapeRun]:
        runs = [r for r in self._store.state.runs.values() if search is None or r.search == search]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    async def extraction_coverage(self, search: SearchName | None) -> ExtractionCoverage:
        state = self._store.state
        latest = self._latest()
        ids = (
            list(state.offers)
            if search is None
            else [oid for (s, oid) in state.links if s == search]
        )
        runs = {r.id.value for r in state.runs.values() if search is None or r.search == search}
        jobs: dict[str, int] = {}
        for job in state.jobs.values():
            if job.type is JobType.EXTRACT_OFFER and (
                search is None or (job.run_id is not None and job.run_id.value in runs)
            ):
                jobs[job.status.value] = jobs.get(job.status.value, 0) + 1
        return ExtractionCoverage(len(ids), sum(1 for i in ids if i in latest), jobs)

    async def attribute_fill(
        self, category: CategoryName, attributes: Sequence[str], search: SearchName | None
    ) -> list[AttributeFill]:
        latest = [
            e
            for e in self._latest().values()
            if e.category == category
            and (search is None or (search, e.offer_id) in self._store.state.links)
        ]
        return [
            AttributeFill(
                category,
                name,
                len(latest),
                sum(1 for e in latest if e.attributes.get(name) is not None),
            )
            for name in attributes
        ]

    async def tables(self) -> list[TableInfo]:
        return [TableInfo("offers", [ColumnInfo("title", "TEXT", True, False)])]

    async def execute_sql(self, sql: str, *, max_rows: int, timeout_seconds: float) -> SqlResult:
        self.sql_calls.append((sql, max_rows, timeout_seconds))
        if "bad" in sql:
            raise InvalidRequestError("SQL error: nope")
        return self.sql_result

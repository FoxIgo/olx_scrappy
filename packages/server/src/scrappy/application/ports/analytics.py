"""Read side for the agent query interface (ADR 0009): plain typed rows, no domain logic.

Like :mod:`scrappy.application.ports.queries` this reads committed data only and is not
part of the unit of work. The use cases under ``application/use_cases/analytics`` do the
filtering that is not expressible portably (attribute predicates), the statistics and the
caveat notes; adapters only fetch.

Semantics every adapter must honour:

* ``offer_rows``: one row per offer; ``category``/``attributes``/``extracted_at`` come from
  the offer's **latest** extraction (newest ``extracted_at``, then last inserted), ``None``
  / empty when it has none. With ``scope.search`` the offer must be linked to that search and
  ``links`` holds only that link; without it, ``links`` holds every link of the offer.
  Relevance is the effective one (override wins over derived). With ``relevant_only`` and no
  search, an offer qualifies when it is relevant in *at least one* search. Order unspecified.
* ``execute_sql``: strictly read-only; one ``SELECT``/``WITH`` statement; at most
  ``max_rows`` rows (``truncated`` when more existed); aborted after ``timeout_seconds``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from scrappy.domain.category import AttributeValue, CategoryName
from scrappy.domain.offer import OfferId, OfferSnapshot, OfferStatus, PriceKind
from scrappy.domain.run import ScrapeRun
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer


@dataclass(frozen=True, slots=True)
class OfferScope:
    search: SearchName | None = None
    relevant_only: bool = False
    statuses: frozenset[OfferStatus] = frozenset()
    """Empty = any status."""
    category: CategoryName | None = None
    """Category of the latest extraction."""


@dataclass(frozen=True, slots=True)
class OfferRow:
    offer_id: OfferId
    url: str
    title: str | None
    location: str | None
    status: OfferStatus
    price_kind: PriceKind | None
    price_amount: Decimal | None
    price_currency: str | None
    price_negotiable: bool | None
    first_seen_at: datetime
    last_seen_at: datetime
    category: CategoryName | None = None
    attributes: Mapping[str, AttributeValue | None] = field(
        default_factory=dict[str, AttributeValue | None]
    )
    extracted_at: datetime | None = None
    links: tuple[SearchOffer, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchCounts:
    search: SavedSearch
    offers: int
    relevant: int
    irrelevant: int
    unknown: int
    extracted: int


@dataclass(frozen=True, slots=True)
class OverviewRows:
    dialect: str
    searches: Sequence[SearchCounts]
    offers_total: int
    offers_extracted: int
    snapshots_total: int
    runs_total: int


@dataclass(frozen=True, slots=True)
class ExtractionCoverage:
    offers: int
    extracted: int


@dataclass(frozen=True, slots=True)
class AttributeFill:
    category: CategoryName
    attribute: str
    extracted: int
    """Offers whose latest extraction is in this category."""
    filled: int
    """... of which have a non-null value for the attribute."""


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    columns: Sequence[ColumnInfo]


@dataclass(frozen=True, slots=True)
class SqlResult:
    columns: tuple[str, ...]
    rows: list[tuple[object, ...]]
    truncated: bool


class AnalyticsQueries(Protocol):
    @property
    def dialect(self) -> str:
        """``sqlite`` or ``postgresql``."""
        ...

    async def offer_rows(self, scope: OfferScope) -> list[OfferRow]: ...

    async def count_offers(self, scope: OfferScope) -> int: ...

    async def overview(self) -> OverviewRows: ...

    async def snapshots(
        self, *, offer_ids: Sequence[OfferId] | None = None, since: datetime | None = None
    ) -> list[OfferSnapshot]:
        """Newest first. ``offer_ids=None`` = all offers."""
        ...

    async def recent_runs(self, search: SearchName | None, limit: int) -> list[ScrapeRun]:
        """Newest first."""
        ...

    async def extraction_coverage(self, search: SearchName | None) -> ExtractionCoverage: ...

    async def attribute_fill(
        self, category: CategoryName, attributes: Sequence[str], search: SearchName | None
    ) -> list[AttributeFill]: ...

    async def tables(self) -> list[TableInfo]: ...

    async def execute_sql(
        self, sql: str, *, max_rows: int, timeout_seconds: float
    ) -> SqlResult: ...

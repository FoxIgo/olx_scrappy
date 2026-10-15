"""Read side: listing and filtering stored offers (R5, R12).

Kept apart from the write repositories so the SQLite adapter can use JSON1/FTS5 (and a
Postgres one JSONB/tsvector) without touching the domain. Reads committed data only; not
part of the unit of work.

:func:`matches_filter` is the reference semantics: adapters must return exactly the items
for which it is true, ordered by ``last_seen_at`` descending (the link's when filtering by
search, else the offer's), then by offer id ascending, with ``offset``/``limit`` applied
after filtering.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import AttributePredicate, OfferExtraction
from scrappy.domain.offer import Offer, OfferStatus
from scrappy.domain.search import SearchName, SearchOffer
from scrappy.domain.shared import InvalidValueError


class RelevanceFilter(StrEnum):
    ALL = "all"
    RELEVANT = "relevant"
    """Effective relevance is True."""
    NOT_IRRELEVANT = "not_irrelevant"
    """True or still unknown (not classified yet): hides only known junk."""
    IRRELEVANT = "irrelevant"


class LivenessFilter(StrEnum):
    ALL = "all"
    ALIVE = "alive"
    """Score >= 65, active seller, fresh listing."""
    STALE = "stale"
    """Score 35..64, borderline activity."""
    ZOMBIE = "zombie"
    """Score < 35, dead/abandoned listing or ghost auto-renew."""


@dataclass(frozen=True, slots=True)
class OfferFilter:
    search: SearchName | None = None
    """Restrict to offers found by this search (required for relevance filtering)."""
    relevance: RelevanceFilter = RelevanceFilter.ALL
    liveness: LivenessFilter = LivenessFilter.ALL
    statuses: frozenset[OfferStatus] = frozenset()
    """Empty = any status."""
    category: CategoryName | None = None
    """Restrict to offers whose latest extraction has this category."""
    attributes: tuple[AttributePredicate, ...] = ()
    """All must match the latest extraction's attributes (AND)."""
    has_delivery: bool | None = None
    """Restrict to offers with or without delivery (None = any)."""
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.relevance is not RelevanceFilter.ALL and self.search is None:
            raise InvalidValueError("relevance is per search: set search to filter by it")
        if self.limit < 1 or self.offset < 0:
            raise InvalidValueError("limit must be >= 1 and offset >= 0")


@dataclass(frozen=True, slots=True)
class OfferListItem:
    offer: Offer
    link: SearchOffer | None
    """The search link when filtering by search, else ``None``."""
    extraction: OfferExtraction | None
    """Latest extraction, if any."""


def matches_filter(item: OfferListItem, query: OfferFilter) -> bool:
    """Reference semantics of :class:`OfferFilter` for one candidate item."""
    if query.search is not None and (item.link is None or item.link.search != query.search):
        return False
    if query.statuses and item.offer.status not in query.statuses:
        return False
    if query.has_delivery is not None and item.offer.has_delivery != query.has_delivery:
        return False
    if (
        query.liveness is not LivenessFilter.ALL
        and item.offer.liveness.status.value != query.liveness.value
    ):
        return False
    relevant = item.link.is_relevant if item.link is not None else None
    match query.relevance:
        case RelevanceFilter.ALL:
            pass
        case RelevanceFilter.RELEVANT:
            if relevant is not True:
                return False
        case RelevanceFilter.NOT_IRRELEVANT:
            if relevant is False:
                return False
        case RelevanceFilter.IRRELEVANT:
            if relevant is not False:
                return False
    extraction = item.extraction
    if query.category is not None and (extraction is None or extraction.category != query.category):
        return False
    if query.attributes:
        if extraction is None:
            return False
        return all(p.matches(extraction.attributes) for p in query.attributes)
    return True


class OfferQueries(Protocol):
    async def list_offers(self, query: OfferFilter) -> list[OfferListItem]: ...

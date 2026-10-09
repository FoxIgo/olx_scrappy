"""Saved searches, the search<->offer link, and the relevance rule (R10, R14)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scrappy.domain.category import CategoryName
from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import OfferId
from scrappy.domain.shared import InvalidValueError, SourceId, require_aware, validate_slug


@dataclass(frozen=True, slots=True, order=True)
class SearchName:
    """Unique, human-chosen name of a saved search, e.g. ``gtx-laptops``. Its identity."""

    value: str

    def __post_init__(self) -> None:
        validate_slug(self.value, "search name")

    def __str__(self) -> str:
        return self.value


@dataclass(eq=False, slots=True)
class SavedSearch:
    """A search URL copied from the browser, on one source, targeting one category."""

    name: SearchName
    source: SourceId
    url: str
    category: CategoryName
    created_at: datetime
    last_run_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise InvalidValueError(f"search URL must be http(s): {self.url!r}")
        require_aware(self.created_at, "created_at")

    def same_definition(self, source: SourceId, url: str, category: CategoryName) -> bool:
        return (self.source, self.url, self.category) == (source, url, category)

    def mark_run_started(self, at: datetime) -> None:
        self.last_run_at = require_aware(at, "at")


def relevance(
    search: SavedSearch, extraction: OfferExtraction | None, override: bool | None = None
) -> bool | None:
    """Is this offer relevant for this search? ``None`` = unknown (not classified yet).

    A manual override always wins; otherwise the offer is relevant when it was classified
    into the search's target category (ADR 0007). Finer intent is attribute filtering.
    """
    if override is not None:
        return override
    if extraction is None:
        return None
    return extraction.category == search.category


@dataclass(eq=False, slots=True)
class SearchOffer:
    """Per-search view of a global offer (many-to-many link, R10)."""

    search: SearchName
    offer_id: OfferId
    first_seen_at: datetime
    last_seen_at: datetime
    derived_relevance: bool | None = None
    """Derived from the latest extraction; ``None`` until the offer is classified."""
    relevance_override: bool | None = None
    """Manual decision; ``None`` = no override. Survives re-extraction."""

    def __post_init__(self) -> None:
        require_aware(self.first_seen_at, "first_seen_at")
        require_aware(self.last_seen_at, "last_seen_at")

    @classmethod
    def first_seen(cls, search: SearchName, offer_id: OfferId, at: datetime) -> SearchOffer:
        return cls(search=search, offer_id=offer_id, first_seen_at=at, last_seen_at=at)

    @property
    def is_relevant(self) -> bool | None:
        """Effective relevance: override, else derived."""
        if self.relevance_override is not None:
            return self.relevance_override
        return self.derived_relevance

    def mark_seen(self, at: datetime) -> None:
        require_aware(at, "at")
        if at > self.last_seen_at:
            self.last_seen_at = at

    def update_relevance(self, search: SavedSearch, extraction: OfferExtraction | None) -> None:
        if search.name != self.search:
            raise InvalidValueError("relevance computed with a different search")
        self.derived_relevance = relevance(search, extraction)

    def set_override(self, value: bool | None) -> None:
        self.relevance_override = value

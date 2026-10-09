"""``ListingSource``: the only thing the application knows about scraping (ADR 0004).

One implementation per site recipe (``olx_pl``, ``allegro_pl``...). Engines, rate limits,
retries inside one request, fallbacks and raw-page archiving are internal to the adapter.

The port is shaped for the two-phase pipeline (ADR 0006): one call fetches **one** search
page (DiscoverPage job) and one call fetches **one** offer (EnrichOffer job). The application
owns pagination state (it stores the next :class:`PageRef` in the next job), so a run can
stop and resume between any two pages.

Contract for adapter authors
----------------------------
* Never raise for *expected* failures. Classify them in the result's ``outcome``:
  BLOCKED / TRANSIENT (retry later), NOT_FOUND / GONE (valid answers). An unexpected
  exception is treated by the worker like TRANSIENT.
* Validate every record (ADR 0005) before building an observation. Records that fail are
  reported as :class:`RecordRejection` (with a raw page reference when archived); they never
  become observations. ``None`` in an observation means "not observed", never "empty".
* Report what you got, nothing more: the application decides what a NOT_FOUND means for a
  known offer (it becomes REMOVED, see ``status_after_fetch``). Do not consult storage.
* Calls must be safe to repeat (they are read-only on the site).
* ``validate_search_url`` is a pure, offline check (no network): a saved search must be
  rejected when it is created, not when its first run fails (R10).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from scrappy.domain.offer import OfferId, OfferObservation, OfferStatus
from scrappy.domain.shared import FetchOutcome, InvalidValueError, SourceId


@dataclass(frozen=True, slots=True)
class PageRef:
    """Reference to one search-results page.

    ``cursor`` is opaque to the application and is stored verbatim in job payloads, so it
    must be a plain string (typically the page URL or the site's own "next" API URL).
    The first page's cursor is the saved search URL; the source maps it as it needs.
    """

    cursor: str
    number: int
    """1-based page number, for the max-pages safety cap and reporting."""

    def __post_init__(self) -> None:
        if not self.cursor:
            raise InvalidValueError("PageRef.cursor must not be empty")
        if self.number < 1:
            raise InvalidValueError("PageRef.number is 1-based")

    @classmethod
    def first(cls, search_url: str) -> PageRef:
        return cls(search_url, 1)


@dataclass(frozen=True, slots=True)
class RecordRejection:
    """A record that failed validation (ADR 0005). Counted, logged, never stored."""

    reason: str
    external_id: str | None = None
    raw_ref: str | None = None
    """Reference to the archived raw page, if the adapter archives pages."""


@dataclass(frozen=True, slots=True)
class SearchPageResult:
    """Result of fetching one search page.

    Past the last page a site may answer OK with no observations and no ``next_page``;
    that is a normal end, not an error. Observations may repeat (promoted offers); the
    application deduplicates by offer id.
    """

    outcome: FetchOutcome
    observations: tuple[OfferObservation, ...] = ()
    rejections: tuple[RecordRejection, ...] = ()
    next_page: PageRef | None = None
    total_results: int | None = None
    """Total number of results the site reports for the search, if it says."""
    truncated: bool = False
    """The site has more results than its pagination can reach (OLX caps at ~1000)."""
    retry_after: timedelta | None = None
    """For BLOCKED/TRANSIENT: a hint (e.g. ``Retry-After``) for the next attempt."""
    message: str | None = None
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is not FetchOutcome.OK and (
            self.observations or self.rejections or self.next_page
        ):
            raise InvalidValueError("only an OK search page carries records or a next page")

    @classmethod
    def failed(
        cls,
        outcome: FetchOutcome,
        message: str | None = None,
        *,
        retry_after: timedelta | None = None,
        raw_ref: str | None = None,
    ) -> SearchPageResult:
        return cls(outcome, message=message, retry_after=retry_after, raw_ref=raw_ref)


@dataclass(frozen=True, slots=True)
class OfferDetailsRequest:
    offer_id: OfferId
    url: str | None
    """Known offer URL, or ``None`` when refreshing an id never stored (API-based recipes
    can work from the id alone; HTML recipes may answer NOT_FOUND)."""


@dataclass(frozen=True, slots=True)
class OfferDetailsResult:
    """Result of fetching one offer.

    * OK: exactly one of ``observation`` (a DETAILS-level observation of the requested
      offer) or ``rejection`` (the page loaded but the record failed validation).
    * GONE: the offer page says removed/sold; ``observed_status`` carries SOLD or REMOVED
      when the recipe can tell.
    * NOT_FOUND: the site says the offer does not exist (404 / "Ad not found").
    * BLOCKED / TRANSIENT: nothing was learned; ``retry_after`` is an optional hint.
    """

    outcome: FetchOutcome
    observation: OfferObservation | None = None
    rejection: RecordRejection | None = None
    observed_status: OfferStatus | None = None
    retry_after: timedelta | None = None
    message: str | None = None
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        has_record = self.observation is not None or self.rejection is not None
        if self.outcome is FetchOutcome.OK:
            if (self.observation is None) == (self.rejection is None):
                raise InvalidValueError("an OK result has exactly one observation or rejection")
            if self.observation is not None and not self.observation.is_detail_complete:
                raise InvalidValueError("offer details must be a DETAILS-level observation")
        elif has_record:
            raise InvalidValueError(f"a {self.outcome.value} result carries no record")
        if self.observed_status is not None and self.outcome is not FetchOutcome.GONE:
            raise InvalidValueError("observed_status is only for GONE results")

    @classmethod
    def ok(cls, observation: OfferObservation, *, raw_ref: str | None = None) -> OfferDetailsResult:
        return cls(FetchOutcome.OK, observation=observation, raw_ref=raw_ref)

    @classmethod
    def rejected(cls, rejection: RecordRejection) -> OfferDetailsResult:
        return cls(FetchOutcome.OK, rejection=rejection, raw_ref=rejection.raw_ref)

    @classmethod
    def gone(
        cls, status: OfferStatus | None = None, message: str | None = None
    ) -> OfferDetailsResult:
        return cls(FetchOutcome.GONE, observed_status=status, message=message)

    @classmethod
    def not_found(cls, message: str | None = None) -> OfferDetailsResult:
        return cls(FetchOutcome.NOT_FOUND, message=message)

    @classmethod
    def failed(
        cls,
        outcome: FetchOutcome,
        message: str | None = None,
        *,
        retry_after: timedelta | None = None,
    ) -> OfferDetailsResult:
        if not outcome.is_retryable:
            raise InvalidValueError("failed() is for BLOCKED / TRANSIENT")
        return cls(outcome, message=message, retry_after=retry_after)


class ListingSource(Protocol):
    @property
    def source_id(self) -> SourceId: ...

    def validate_search_url(self, url: str) -> None:
        """Check that ``url`` is a search URL this recipe can run.

        Pure and synchronous (no I/O). Raise :class:`~scrappy.application.errors.
        InvalidRequestError` with a user-facing reason when the URL is unsupported
        (wrong host, a path shape the recipe cannot translate, ...); return otherwise.
        Called by ``AddSavedSearch`` before the search is stored.
        """
        ...

    async def fetch_search_page(self, page: PageRef) -> SearchPageResult:
        """Fetch and parse one search page; also report the next page, if any.

        A source whose search results already contain full offer data (e.g. OLX's API)
        returns DETAILS-level observations; the application then skips EnrichOffer.
        """
        ...

    async def fetch_offer_details(self, request: OfferDetailsRequest) -> OfferDetailsResult:
        """Fetch and parse one offer page (or API detail)."""
        ...


type ListingSources = Mapping[SourceId, ListingSource]
"""Registry of sources by id, built in ``main.py`` from config (ADR 0004)."""

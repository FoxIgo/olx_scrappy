"""``OlxPlListingSource``: the olx.pl recipe behind the ``ListingSource`` port.

Primary path is the internal JSON API (spike, R16): search items are detail-complete, so
every observation is DETAILS level and the EnrichOffer stage is skipped.

Category-path search URLs (``/elektronika/komputery/laptopy/q-...``) have no known
URL -> API mapping, so page 1 is fetched as HTML and parsed from the embedded state
(``html_state.py``); the state's ``links.next`` is an API URL carrying ``category_id``, the
query and the filters, and every later page goes through the API path.
"""

from __future__ import annotations

import json
from typing import Any

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.listing_source import (
    OfferDetailsRequest,
    OfferDetailsResult,
    PageRef,
    RecordRejection,
    SearchPageResult,
)
from scrappy.domain.offer import OfferStatus
from scrappy.domain.shared import FetchOutcome, SourceId
from scrappy.infrastructure.scraping.engines.base import (
    FetchBlocked,
    FetchError,
    FetchRequest,
    PageFetcher,
    RawPage,
)

from .classifier import Classification, PageKind, classify_api, retry_after_of
from .html_state import search_result_from_html
from .mapper import SOURCE_ID, RecordInvalid, map_api_offer, status_from_text
from .schemas import ApiSearchEnvelope
from .search_page import ParsedSearchPage, assemble_search_result
from .urls import (
    DEFAULT_PAGE_SIZE,
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    CursorKind,
    UnsupportedSearchUrl,
    build_search_request,
    classify_cursor,
    first_page_ref,
    offer_api_url,
)

_HEADERS = {"Accept": "application/json", "Accept-Language": "pl-PL,pl;q=0.9"}
_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9",
}


class OlxPlListingSource:
    def __init__(
        self,
        fetcher: PageFetcher,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        require_price: bool = True,
        timeout: float = 30.0,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be 1..{MAX_PAGE_SIZE} (OLX API limit)")
        self._fetcher = fetcher
        self._page_size = page_size
        self._require_price = require_price
        self._timeout = timeout

    @property
    def source_id(self) -> SourceId:
        return SOURCE_ID

    # ------------------------------------------------------------------ search

    def validate_search_url(self, url: str) -> None:
        """Reject URLs :func:`first_page_ref` cannot translate (offline, no request)."""
        try:
            first_page_ref(url)
        except UnsupportedSearchUrl as exc:
            raise InvalidRequestError(str(exc)) from exc

    async def fetch_search_page(self, page: PageRef) -> SearchPageResult:
        """One search page: HTML for a category-path cursor, the API otherwise. Raises
        ``UnsupportedSearchUrl`` for a cursor that cannot be mapped (a configuration error,
        not a site failure)."""
        if classify_cursor(page.cursor) is CursorKind.CATEGORY_HTML:
            return await self._fetch_category_page(page)
        request = build_search_request(page.cursor, self._page_size)
        if request.offset > MAX_OFFSET:
            return SearchPageResult(FetchOutcome.OK, truncated=True)

        raw = await self._get(request.url)
        if isinstance(raw, Classification):
            return SearchPageResult.failed(raw.fetch_outcome, raw.message)
        verdict = classify_api(raw)
        if verdict.kind is PageKind.RESULT_CAP:
            return SearchPageResult(
                FetchOutcome.OK, truncated=True, message=verdict.message, raw_ref=raw.archive_ref
            )
        if verdict.kind is not PageKind.OK:
            return SearchPageResult.failed(
                verdict.fetch_outcome,
                verdict.message,
                retry_after=retry_after_of(raw),
                raw_ref=raw.archive_ref,
            )
        envelope = _parse_envelope(raw.body)
        if envelope is None:
            return SearchPageResult.failed(
                FetchOutcome.TRANSIENT,
                "unexpected search payload (no data list)",
                raw_ref=raw.archive_ref,
            )
        return assemble_search_result(
            ParsedSearchPage(
                items=envelope.data,
                total_elements=envelope.metadata.total_elements,
                visible_total=envelope.metadata.visible_total_count,
                next_href=envelope.links.next.href if envelope.links.next else None,
            ),
            page=page,
            mapper=map_api_offer,
            require_price=self._require_price,
            raw_ref=raw.archive_ref,
        )

    async def _fetch_category_page(self, page: PageRef) -> SearchPageResult:
        raw = await self._get(page.cursor.strip(), _HTML_HEADERS)
        if isinstance(raw, Classification):
            return SearchPageResult.failed(raw.fetch_outcome, raw.message)
        return search_result_from_html(raw, page, require_price=self._require_price)

    # ------------------------------------------------------------------ details

    async def fetch_offer_details(self, request: OfferDetailsRequest) -> OfferDetailsResult:
        """``GET /api/v1/offers/{id}/``. Works from the id alone (``request.url`` is unused)."""
        external_id = request.offer_id.external_id
        raw = await self._get(offer_api_url(external_id))
        if isinstance(raw, Classification):
            return OfferDetailsResult.failed(raw.fetch_outcome, raw.message)
        verdict = classify_api(raw)
        if verdict.kind is PageKind.NOT_FOUND:
            return OfferDetailsResult.not_found(verdict.message)
        if verdict.kind is not PageKind.OK:
            outcome = (
                FetchOutcome.TRANSIENT
                if verdict.kind is PageKind.RESULT_CAP
                else verdict.fetch_outcome
            )
            return OfferDetailsResult.failed(
                outcome, verdict.message, retry_after=retry_after_of(raw)
            )

        data = _parse_detail(raw.body)
        if data is None:
            return OfferDetailsResult.failed(
                FetchOutcome.TRANSIENT, "unexpected detail payload (no data object)"
            )
        status = data.get("status")
        if isinstance(status, str) and status_from_text(status) is not OfferStatus.ACTIVE:
            return OfferDetailsResult.gone(status_from_text(status), f"offer status {status!r}")
        try:
            observation = map_api_offer(data, require_price=False)
        except RecordInvalid as exc:
            return OfferDetailsResult.rejected(
                RecordRejection(str(exc), external_id, raw.archive_ref)
            )
        if observation.offer_id != request.offer_id:
            return OfferDetailsResult.rejected(
                RecordRejection(
                    f"detail id {observation.offer_id.external_id} differs from requested",
                    external_id,
                    raw.archive_ref,
                )
            )
        return OfferDetailsResult.ok(observation, raw_ref=raw.archive_ref)

    # ------------------------------------------------------------------ transport

    async def _get(self, url: str, headers: dict[str, str] = _HEADERS) -> RawPage | Classification:
        """Fetch; transport errors become TRANSIENT, a raised ``FetchBlocked`` becomes BLOCKED."""
        try:
            raw = await self._fetcher.fetch(
                FetchRequest(url=url, headers=headers, timeout=self._timeout)
            )
        except FetchBlocked as exc:
            return Classification(PageKind.BLOCKED, str(exc))
        except (FetchError, OSError, TimeoutError) as exc:
            return Classification(PageKind.TRANSIENT, f"{type(exc).__name__}: {exc}")
        return raw


def _parse_envelope(body: str) -> ApiSearchEnvelope | None:
    try:
        return ApiSearchEnvelope.model_validate_json(body)
    except ValueError:
        return None


def _parse_detail(body: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None  # pyright: ignore[reportUnknownMemberType]
    return data if isinstance(data, dict) else None  # pyright: ignore[reportUnknownVariableType]

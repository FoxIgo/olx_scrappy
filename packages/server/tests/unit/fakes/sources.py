"""Scripted ListingSource and AttributeExtractor, and the read-side fake."""

from __future__ import annotations

from collections.abc import Callable

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.extractor import (
    ExtractionInput,
    ExtractionRejection,
    ExtractionResult,
)
from scrappy.application.ports.listing_source import (
    OfferDetailsRequest,
    OfferDetailsResult,
    PageRef,
    SearchPageResult,
)
from scrappy.application.ports.queries import OfferFilter, OfferListItem, matches_filter
from scrappy.domain.extraction import OfferExtraction
from scrappy.domain.offer import OfferId
from scrappy.domain.shared import FetchOutcome, SourceId
from tests.unit.fakes.store import InMemoryStore


class ScriptedListingSource:
    """Answers from scripts keyed by page cursor / offer id.

    Each script is a list of results consumed one per call; the last one repeats.
    Unscripted pages answer OK with no records (the end); unscripted offers NOT_FOUND.
    All calls are logged.
    """

    def __init__(self, source_id: str) -> None:
        self._source_id = SourceId(source_id)
        self._pages: dict[str, list[SearchPageResult]] = {}
        self._details: dict[OfferId, list[OfferDetailsResult]] = {}
        self.rejected_urls: dict[str, str] = {}
        """url -> reason; ``validate_search_url`` rejects exactly these."""
        self.validated_urls: list[str] = []
        self.page_calls: list[PageRef] = []
        self.detail_calls: list[OfferDetailsRequest] = []

    @property
    def source_id(self) -> SourceId:
        return self._source_id

    def validate_search_url(self, url: str) -> None:
        self.validated_urls.append(url)
        if url in self.rejected_urls:
            raise InvalidRequestError(self.rejected_urls[url])

    def script_page(self, cursor: str, *results: SearchPageResult) -> None:
        self._pages[cursor] = list(results)

    def script_details(self, offer_id: OfferId, *results: OfferDetailsResult) -> None:
        self._details[offer_id] = list(results)

    async def fetch_search_page(self, page: PageRef) -> SearchPageResult:
        self.page_calls.append(page)
        script = self._pages.get(page.cursor)
        if not script:
            return SearchPageResult(FetchOutcome.OK)
        return script.pop(0) if len(script) > 1 else script[0]

    async def fetch_offer_details(self, request: OfferDetailsRequest) -> OfferDetailsResult:
        self.detail_calls.append(request)
        script = self._details.get(request.offer_id)
        if not script:
            return OfferDetailsResult.not_found()
        return script.pop(0) if len(script) > 1 else script[0]

    def detail_call_ids(self) -> list[OfferId]:
        return [call.offer_id for call in self.detail_calls]


type ExtractorScript = Callable[[ExtractionInput], ExtractionResult | ExtractionRejection]


class ScriptedExtractor:
    def __init__(self, script: ExtractorScript) -> None:
        self.script = script
        self.calls: list[ExtractionInput] = []

    async def extract(self, request: ExtractionInput) -> ExtractionResult | ExtractionRejection:
        self.calls.append(request)
        return self.script(request)


class InMemoryOfferQueries:
    """Reference implementation of ``OfferQueries`` over the committed in-memory state."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def list_offers(self, query: OfferFilter) -> list[OfferListItem]:
        state = self._store.state
        latest: dict[OfferId, OfferExtraction] = {}
        for extraction in state.extractions:  # later insertion wins ties
            current = latest.get(extraction.offer_id)
            if current is None or (
                extraction.provenance.extracted_at >= current.provenance.extracted_at
            ):
                latest[extraction.offer_id] = extraction
        items: list[OfferListItem] = []
        for offer_id, offer in state.offers.items():
            link = state.links.get((query.search, offer_id)) if query.search else None
            item = OfferListItem(offer, link, latest.get(offer_id))
            if matches_filter(item, query):
                items.append(item)

        def order(item: OfferListItem) -> tuple[float, str]:
            seen = item.link.last_seen_at if item.link else item.offer.last_seen_at
            return (-seen.timestamp(), str(item.offer.id))

        items.sort(key=order)
        return items[query.offset : query.offset + query.limit]

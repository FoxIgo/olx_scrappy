from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.listing_source import (
    ListingSource,
    OfferDetailsRequest,
    PageRef,
)
from scrappy.domain.offer import OfferId, OfferStatus
from scrappy.domain.shared import FetchOutcome, SourceId
from scrappy.infrastructure.scraping.engines.base import (
    FetchBlocked,
    FetchTransportError,
)
from scrappy.infrastructure.scraping.sources.olx_pl.source import OlxPlListingSource
from scrappy.infrastructure.scraping.sources.olx_pl.urls import UnsupportedSearchUrl

from .conftest import (
    CLOUDFRONT_403,
    SEARCH_URL,
    FakeFetcher,
    fixture_json,
    fixture_text,
    make_page,
)

OID = OfferId(SourceId("olx_pl"), "1098526767")


def make_source(*results: Any) -> tuple[OlxPlListingSource, FakeFetcher]:
    fetcher = FakeFetcher(*results)
    return OlxPlListingSource(fetcher), fetcher


def test_implements_port() -> None:
    source: ListingSource = OlxPlListingSource(FakeFetcher())
    assert source.source_id == SourceId("olx_pl")


def test_validate_search_url_accepts_supported_url() -> None:
    OlxPlListingSource(FakeFetcher()).validate_search_url(SEARCH_URL)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.allegro.pl/elektronika/komputery/laptopy/",
        "https://www.allegro.pl/oferty/q-laptop/",
        "https://www.olx.pl/oferty/q-laptop/extra/",
        "https://www.olx.pl/oferty/krakow/",
        "https://www.olx.pl/d/oferta/x-CID99-IDabc.html",
        "https://www.olx.pl/a/b/c/d/e/q-x/",
        "https://www.olx.pl/api/v1/offers/?offset=0",
        "https://www.olx.pl/",
    ],
)
def test_validate_search_url_rejects_unsupported_url(url: str) -> None:
    with pytest.raises(InvalidRequestError):
        OlxPlListingSource(FakeFetcher()).validate_search_url(url)


def test_page_size_is_validated() -> None:
    with pytest.raises(ValueError, match="page_size"):
        OlxPlListingSource(FakeFetcher(), page_size=51)


# ------------------------------------------------------------------------------- search


async def test_first_page_maps_all_items_and_links_next(search_page1: dict[str, Any]) -> None:
    source, fetcher = make_source(make_page(search_page1))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.outcome is FetchOutcome.OK
    assert [o.offer_id.external_id for o in result.observations] == [
        "1098526767",
        "1102737468",
        "1102606472",
        "1103596779",
        "1055509373",
    ]
    assert all(o.is_detail_complete for o in result.observations)
    assert result.rejections == ()
    assert result.total_results == 173
    assert result.truncated is False
    assert result.next_page == PageRef(search_page1["links"]["next"]["href"], 2)
    assert [o.promoted for o in result.observations][:3] == [True, True, True]
    # the browser URL was translated to an API request
    (request,) = fetcher.calls
    assert request.url.startswith("https://www.olx.pl/api/v1/offers/?")
    assert "query=gtx%201650%20laptop" in request.url
    assert "limit=40" in request.url
    assert request.headers["Accept"] == "application/json"


async def test_next_cursor_is_followed_verbatim(search_page1: dict[str, Any]) -> None:
    source, fetcher = make_source(make_page(search_page1))
    href = search_page1["links"]["next"]["href"]

    result = await source.fetch_search_page(PageRef(href, 2))

    assert fetcher.calls[0].url == href
    assert result.next_page is not None
    assert result.next_page.number == 3


async def test_promoted_duplicates_are_deduplicated(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["data"].insert(3, copy.deepcopy(payload["data"][0]))
    payload["data"].append(copy.deepcopy(payload["data"][1]))
    source, _ = make_source(make_page(payload))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    ids = [o.offer_id.external_id for o in result.observations]
    assert len(payload["data"]) == 7
    assert len(ids) == len(set(ids)) == 5
    assert ids[0] == "1098526767"


async def test_last_page_has_no_next(search_page1: dict[str, Any]) -> None:
    last = fixture_json("api_search_last_page_no_next.json")
    source, _ = make_source(make_page(last))

    result = await source.fetch_search_page(
        PageRef("https://www.olx.pl/api/v1/offers?offset=160", 5)
    )

    assert result.outcome is FetchOutcome.OK
    assert len(result.observations) == 2
    assert result.next_page is None
    assert result.total_results == 173
    assert result.truncated is False


async def test_beyond_end_is_ok_and_empty() -> None:
    source, _ = make_source(make_page(fixture_json("api_search_beyond_end_empty.json")))

    result = await source.fetch_search_page(
        PageRef("https://www.olx.pl/api/v1/offers?offset=200", 6)
    )

    assert result.outcome is FetchOutcome.OK
    assert result.observations == ()
    assert result.next_page is None
    assert result.truncated is False


async def test_empty_data_never_yields_next_even_with_link(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["data"] = []
    source, _ = make_source(make_page(payload))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.next_page is None


async def test_broad_query_is_truncated(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["metadata"].update(total_elements=1000, visible_total_count=113841)
    source, _ = make_source(make_page(payload))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.total_results == 1000
    assert result.truncated is True


async def test_offset_400_is_end_of_results_not_error() -> None:
    body = fixture_json("api_error_offset_over_1000_400.json")
    source, _ = make_source(make_page(body, 400))

    result = await source.fetch_search_page(
        PageRef("https://www.olx.pl/api/v1/offers?offset=1040", 27)
    )

    assert result.outcome is FetchOutcome.OK
    assert result.observations == ()
    assert result.next_page is None
    assert result.truncated is True


async def test_limit_400_is_end_of_results_too() -> None:
    source, _ = make_source(make_page(fixture_json("api_error_limit_over_50_400.json"), 400))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.OK
    assert result.truncated is True


async def test_unrelated_400_is_transient() -> None:
    body = {"error": {"status": 400, "detail": "Bad query"}}
    source, _ = make_source(make_page(body, 400))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.TRANSIENT


async def test_cursor_beyond_offset_cap_makes_no_request() -> None:
    source, fetcher = make_source(make_page({}))

    result = await source.fetch_search_page(
        PageRef("https://www.olx.pl/api/v1/offers?offset=1040", 27)
    )

    assert result.outcome is FetchOutcome.OK
    assert result.truncated is True
    assert fetcher.calls == []


async def test_next_link_past_cap_is_dropped_and_truncated(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["links"]["next"]["href"] = "https://www.olx.pl/api/v1/offers?offset=1040&limit=40"
    source, _ = make_source(make_page(payload))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.next_page is None
    assert result.truncated is True


async def test_foreign_next_link_is_ignored(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["links"]["next"]["href"] = "https://evil.example/api/v1/offers?offset=40"
    source, _ = make_source(make_page(payload))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.next_page is None


async def test_invalid_item_is_rejected_without_failing_the_page(
    search_page1: dict[str, Any],
) -> None:
    payload = copy.deepcopy(search_page1)
    del payload["data"][1]["title"]
    payload["data"][2]["params"] = [p for p in payload["data"][2]["params"] if p["key"] != "price"]
    payload["data"].append("not an object")
    source, _ = make_source(make_page(payload))

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.outcome is FetchOutcome.OK
    assert [o.offer_id.external_id for o in result.observations] == [
        "1098526767",
        "1103596779",
        "1055509373",
    ]
    assert [r.external_id for r in result.rejections] == ["1102737468", "1102606472", None]
    assert "title" in result.rejections[0].reason
    assert "price" in result.rejections[1].reason


async def test_price_not_required_when_configured(search_page1: dict[str, Any]) -> None:
    payload = copy.deepcopy(search_page1)
    payload["data"][0]["params"] = [p for p in payload["data"][0]["params"] if p["key"] != "price"]
    source = OlxPlListingSource(FakeFetcher(make_page(payload)), require_price=False)
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert len(result.observations) == 5
    assert result.observations[0].price is None


async def test_blocked_cloudfront_403() -> None:
    page = make_page(
        CLOUDFRONT_403,
        403,
        headers={"server": "CloudFront", "x-cache": "Error from cloudfront"},
        content_type="text/html",
    )
    source, _ = make_source(page)

    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))

    assert result.outcome is FetchOutcome.BLOCKED
    assert result.message is not None
    assert "CloudFront" in result.message
    assert result.observations == ()


async def test_cloudfront_body_with_200_is_blocked() -> None:
    source, _ = make_source(make_page(CLOUDFRONT_403, 200, content_type="text/html"))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.BLOCKED


async def test_429_blocked_carries_retry_after() -> None:
    source, _ = make_source(make_page({}, 429, headers={"retry-after": "30"}))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.BLOCKED
    assert result.retry_after == timedelta(seconds=30)


async def test_html_instead_of_json_is_blocked() -> None:
    source, _ = make_source(make_page("<html><body>hi</body></html>", content_type="text/html"))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.BLOCKED


async def test_5xx_and_transport_errors_are_transient() -> None:
    source, _ = make_source(make_page("oops", 502, content_type="text/html"))
    assert (await source.fetch_search_page(PageRef.first(SEARCH_URL))).outcome is (
        FetchOutcome.TRANSIENT
    )

    source, _ = make_source(FetchTransportError("timeout"))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.TRANSIENT
    assert "timeout" in (result.message or "")


async def test_fetch_blocked_exception_is_blocked() -> None:
    page = make_page(CLOUDFRONT_403, 403, content_type="text/html")
    source, _ = make_source(FetchBlocked(page))
    result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.BLOCKED


async def test_garbage_json_is_transient() -> None:
    source, _ = make_source(make_page("{not json"))
    assert (await source.fetch_search_page(PageRef.first(SEARCH_URL))).outcome is (
        FetchOutcome.TRANSIENT
    )
    source, _ = make_source(make_page({"unexpected": 1}))
    assert (await source.fetch_search_page(PageRef.first(SEARCH_URL))).outcome is (
        FetchOutcome.TRANSIENT
    )


async def test_region_url_raises_unsupported() -> None:
    source, fetcher = make_source(make_page({}))
    with pytest.raises(UnsupportedSearchUrl):
        await source.fetch_search_page(PageRef.first("https://www.olx.pl/oferty/krakow/"))
    assert fetcher.calls == []


# ------------------------------------------------------------------------------- details


async def test_offer_details_ok() -> None:
    source, fetcher = make_source(make_page(fixture_json("api_offer_detail.json")))

    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))

    assert result.outcome is FetchOutcome.OK
    assert result.observation is not None
    assert result.observation.offer_id == OID
    assert result.observation.is_detail_complete
    assert result.observation.title is not None
    assert fetcher.calls[0].url == "https://www.olx.pl/api/v1/offers/1098526767/"


async def test_offer_details_not_found_api_json() -> None:
    source, _ = make_source(make_page(fixture_json("api_offer_not_found_404.json"), 404))
    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))
    assert result.outcome is FetchOutcome.NOT_FOUND
    assert "Ad not found" in (result.message or "")


async def test_offer_details_not_found_legacy_body() -> None:
    page = make_page(
        fixture_json("api_offer_bad_id_404.json"), 404, content_type="application/x-json"
    )
    source, _ = make_source(page)
    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))
    assert result.outcome is FetchOutcome.NOT_FOUND


async def test_offer_details_not_found_html_404() -> None:
    page = make_page(fixture_text("offer_not_found_404.html"), 404, content_type="text/html")
    source, _ = make_source(page)
    assert (await source.fetch_offer_details(OfferDetailsRequest(OID, None))).outcome is (
        FetchOutcome.NOT_FOUND
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [("removed_by_user", OfferStatus.REMOVED), ("sold", OfferStatus.SOLD)],
)
async def test_non_active_offer_is_gone(status: str, expected: OfferStatus) -> None:
    payload = fixture_json("api_offer_detail.json")
    payload["data"]["status"] = status
    source, _ = make_source(make_page(payload))

    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))

    assert result.outcome is FetchOutcome.GONE
    assert result.observed_status is expected


async def test_offer_details_blocked_and_transient() -> None:
    source, _ = make_source(make_page(CLOUDFRONT_403, 403, content_type="text/html"))
    assert (await source.fetch_offer_details(OfferDetailsRequest(OID, None))).outcome is (
        FetchOutcome.BLOCKED
    )
    source, _ = make_source(FetchTransportError("reset"))
    assert (await source.fetch_offer_details(OfferDetailsRequest(OID, None))).outcome is (
        FetchOutcome.TRANSIENT
    )


async def test_offer_details_invalid_record_is_rejected() -> None:
    payload = fixture_json("api_offer_detail.json")
    del payload["data"]["description"]
    source, _ = make_source(make_page(payload))

    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))

    assert result.outcome is FetchOutcome.OK
    assert result.observation is None
    assert result.rejection is not None
    assert result.rejection.external_id == "1098526767"
    assert "description" in result.rejection.reason


async def test_offer_details_id_mismatch_is_rejected() -> None:
    source, _ = make_source(make_page(fixture_json("api_offer_detail.json")))
    other = OfferId(SourceId("olx_pl"), "42")
    result = await source.fetch_offer_details(OfferDetailsRequest(other, None))
    assert result.rejection is not None
    assert "differs" in result.rejection.reason


async def test_offer_details_without_price_is_accepted() -> None:
    payload = fixture_json("api_offer_detail.json")
    payload["data"]["params"] = [p for p in payload["data"]["params"] if p["key"] != "price"]
    source, _ = make_source(make_page(payload))
    result = await source.fetch_offer_details(OfferDetailsRequest(OID, None))
    assert result.observation is not None
    assert result.observation.price is None

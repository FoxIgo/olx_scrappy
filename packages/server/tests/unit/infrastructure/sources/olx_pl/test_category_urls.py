"""Category-path search URLs: page 1 via HTML state, later pages via the API."""

from __future__ import annotations

import pytest

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.shared import FetchOutcome
from scrappy.infrastructure.scraping.engines.base import FetchBlocked
from scrappy.infrastructure.scraping.sources.olx_pl.source import OlxPlListingSource
from scrappy.infrastructure.scraping.sources.olx_pl.urls import (
    CursorKind,
    UnsupportedSearchUrl,
    build_search_request,
    classify_cursor,
    first_page_ref,
)

from .conftest import CLOUDFRONT_403, SEARCH_URL, FakeFetcher, fixture_text, make_page

NITRO_7 = "https://www.olx.pl/elektronika/komputery/laptopy/q-acer-nitro-7/"
USER_URLS = [
    "https://www.olx.pl/elektronika/komputery/laptopy/q-Nitro-7-AN715-51/",
    NITRO_7,
    "https://www.olx.pl/elektronika/komputery/laptopy/q-acer-nitro-5/",
]
FILTERED = (
    NITRO_7 + "?search%5Border%5D=filter_float_price:asc&search%5Bfilter_float_price:to%5D=3000"
)
NEXT_HREF = (
    "https://www.olx.pl/api/v1/offers?offset=38&limit=40&query=acer+nitro+7&category_id=1199"
    "&suggest_filters=true&return_filters=true"
)


def html_page(body: str, status: int = 200):
    return make_page(body, status, url=NITRO_7, content_type="text/html")


@pytest.mark.parametrize(
    "url",
    [
        *USER_URLS,
        FILTERED,
        "https://www.olx.pl/elektronika/komputery/laptopy/",
        "https://olx.pl/elektronika/",
        "https://www.olx.pl/elektronika/komputery/laptopy/?page=2",
        "https://www.olx.pl/a/b/c/d/q-x/",
        "https://www.olx.pl/elektronika/komputery/laptopy/q-acer-nitro-7",
    ],
)
def test_category_urls_are_valid_and_fetched_as_html(url: str) -> None:
    OlxPlListingSource(FakeFetcher()).validate_search_url(url)
    assert classify_cursor(url) is CursorKind.CATEGORY_HTML
    assert first_page_ref(url) == PageRef(url, 1)


def test_other_cursors_keep_their_kind() -> None:
    assert classify_cursor(SEARCH_URL) is CursorKind.TRANSLATED
    assert classify_cursor("https://www.olx.pl/oferty/") is CursorKind.TRANSLATED
    assert classify_cursor(NEXT_HREF) is CursorKind.API
    assert build_search_request(NEXT_HREF).url == NEXT_HREF  # old API cursors still work


@pytest.mark.parametrize(
    "url", ["https://www.olx.pl/oferty/krakow/", "https://www.olx.pl/a/b/c/d/e/"]
)
def test_unsupported_shapes_are_rejected(url: str) -> None:
    with pytest.raises(UnsupportedSearchUrl):
        first_page_ref(url)
    with pytest.raises(InvalidRequestError):
        OlxPlListingSource(FakeFetcher()).validate_search_url(url)


async def test_page1_via_html_then_page2_via_api() -> None:
    fetcher = FakeFetcher(
        html_page(fixture_text("category_search_results.html")),
        make_page(fixture_text("api_category_search_page2.json")),
    )
    source = OlxPlListingSource(fetcher)

    first = await source.fetch_search_page(PageRef.first(FILTERED))

    assert first.outcome is FetchOutcome.OK
    assert [o.offer_id.external_id for o in first.observations] == [
        "1096264223",
        "1103261988",
        "1100064449",
        "1103680453",
    ]
    assert first.total_results == 231
    assert first.truncated is False
    assert first.next_page == PageRef(NEXT_HREF, 2)
    assert fetcher.calls[0].url == FILTERED
    assert "text/html" in fetcher.calls[0].headers["Accept"]

    assert first.next_page is not None
    second = await source.fetch_search_page(first.next_page)

    assert second.outcome is FetchOutcome.OK
    assert [o.offer_id.external_id for o in second.observations] == [
        "1096137457",
        "1100536849",
        "1102324894",
    ]
    assert second.total_results == 231
    assert len(fetcher.calls) == 2
    assert fetcher.calls[1].url == NEXT_HREF
    assert fetcher.calls[1].headers["Accept"] == "application/json"
    assert "category_id=1199" in fetcher.calls[1].url


async def test_old_translated_cursor_still_uses_api() -> None:
    fetcher = FakeFetcher(make_page(fixture_text("api_search_page1.json")))
    result = await OlxPlListingSource(fetcher).fetch_search_page(PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.OK
    assert fetcher.calls[0].url.startswith("https://www.olx.pl/api/v1/offers/?")


async def test_cloudfront_403_on_html_page_is_blocked() -> None:
    source = OlxPlListingSource(FakeFetcher(html_page(CLOUDFRONT_403, 403)))
    result = await source.fetch_search_page(PageRef.first(NITRO_7))
    assert result.outcome is FetchOutcome.BLOCKED
    assert result.observations == ()


async def test_raised_block_on_html_page_is_blocked() -> None:
    source = OlxPlListingSource(FakeFetcher(FetchBlocked(html_page(CLOUDFRONT_403, 403))))
    result = await source.fetch_search_page(PageRef.first(NITRO_7))
    assert result.outcome is FetchOutcome.BLOCKED


async def test_html_without_state_is_blocked() -> None:
    source = OlxPlListingSource(FakeFetcher(html_page("<html><body>hi</body></html>")))
    result = await source.fetch_search_page(PageRef.first(NITRO_7))
    assert result.outcome is FetchOutcome.BLOCKED


async def test_server_error_on_html_page_is_transient() -> None:
    source = OlxPlListingSource(FakeFetcher(html_page("oops", 503)))
    result = await source.fetch_search_page(PageRef.first(NITRO_7))
    assert result.outcome is FetchOutcome.TRANSIENT


async def test_empty_category_page_is_ok_without_next() -> None:
    body = fixture_text("category_search_results.html").replace(
        '\\"ads\\":[', '\\"ads\\":[],\\"_x\\":['
    )
    result = await OlxPlListingSource(FakeFetcher(html_page(body))).fetch_search_page(
        PageRef.first(NITRO_7)
    )
    assert result.outcome is FetchOutcome.OK
    assert result.next_page is None

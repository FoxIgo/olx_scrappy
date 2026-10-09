from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from scrappy.application.ports.listing_source import PageRef
from scrappy.infrastructure.scraping.sources.olx_pl.urls import (
    UnsupportedSearchUrl,
    build_search_request,
    first_page_ref,
    next_page_ref,
    offer_api_url,
    translate_search_url,
)

from .conftest import SEARCH_URL


def test_spike_url_translates_to_api_params() -> None:
    params, warnings = translate_search_url(SEARCH_URL)
    assert params == {
        "query": "gtx 1650 laptop",
        "sort_by": "filter_float_price:asc",
        "filter_float_price:from": "600",
        "filter_float_price:to": "1400",
        "offset": "0",
        "limit": "40",
    }
    assert warnings == ()


def test_page_number_becomes_offset() -> None:
    params, _ = translate_search_url("https://www.olx.pl/oferty/q-iphone/?page=3", page_size=20)
    assert (params["offset"], params["limit"]) == ("40", "20")


def test_invalid_page_is_ignored_with_warning() -> None:
    params, warnings = translate_search_url("https://www.olx.pl/oferty/q-x/?page=abc")
    assert params["offset"] == "0"
    assert any("page" in w for w in warnings)


def test_no_query_segment_is_allowed() -> None:
    params, _ = translate_search_url(
        "https://www.olx.pl/oferty/?search%5Bfilter_float_price:to%5D=5"
    )
    assert "query" not in params
    assert params["filter_float_price:to"] == "5"


def test_percent_encoded_slug_is_decoded() -> None:
    params, _ = translate_search_url("https://www.olx.pl/oferty/q-zam%C3%B3wienie-psa/")
    assert params["query"] == "zamówienie psa"


def test_enum_filter_array_suffix_is_kept_without_warning() -> None:
    url = "https://www.olx.pl/oferty/q-a/?search%5Bfilter_enum_state%5D%5B0%5D=used"
    params, warnings = translate_search_url(url)
    assert params["filter_enum_state[0]"] == "used"
    assert warnings == ()


def test_unknown_params_pass_through_with_warnings() -> None:
    url = "https://www.olx.pl/oferty/q-a/?search%5Bdist%5D=30&reason=observed_search"
    params, warnings = translate_search_url(url)
    assert params["dist"] == "30"
    assert params["reason"] == "observed_search"
    assert len(warnings) == 2


@pytest.mark.parametrize(
    "url",
    [
        "https://www.olx.pl/elektronika/komputery/laptopy/q-gtx/",
        "https://www.olx.pl/elektronika/",
        "https://www.olx.pl/oferty/krakow/",
        "https://www.olx.pl/oferty/q-a/extra/",
        "https://www.olx.pl/",
    ],
)
def test_category_and_region_paths_are_unsupported(url: str) -> None:
    with pytest.raises(UnsupportedSearchUrl, match=r"HTML-state|category"):
        translate_search_url(url)


def test_foreign_host_is_unsupported() -> None:
    with pytest.raises(UnsupportedSearchUrl, match=r"olx\.pl"):
        translate_search_url("https://example.com/oferty/q-a/")


def test_build_search_request_from_browser_url() -> None:
    request = build_search_request(SEARCH_URL)
    parts = urlsplit(request.url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "www.olx.pl", "/api/v1/offers/")
    assert dict(parse_qsl(parts.query))["query"] == "gtx 1650 laptop"
    assert request.offset == 0


def test_build_search_request_from_next_href_is_verbatim() -> None:
    href = "https://www.olx.pl/api/v1/offers?offset=80&limit=40&query=gtx+1650+laptop"
    request = build_search_request(href)
    assert request.url == href
    assert request.offset == 80


def test_foreign_api_cursor_is_refused() -> None:
    with pytest.raises(UnsupportedSearchUrl):
        build_search_request("https://evil.example/api/v1/offers?offset=40")


def test_page_refs() -> None:
    first = first_page_ref(SEARCH_URL)
    assert (first.cursor, first.number) == (SEARCH_URL, 1)
    nxt = next_page_ref("https://www.olx.pl/api/v1/offers?offset=40&limit=40", first)
    assert nxt == PageRef("https://www.olx.pl/api/v1/offers?offset=40&limit=40", 2)
    assert next_page_ref("https://other.example/api/v1/offers?offset=40", first) is None
    with pytest.raises(UnsupportedSearchUrl):
        first_page_ref("https://www.olx.pl/elektronika/")


def test_offer_api_url() -> None:
    assert offer_api_url("1098526767") == "https://www.olx.pl/api/v1/offers/1098526767/"
    assert offer_api_url("a/b") == "https://www.olx.pl/api/v1/offers/a%2Fb/"

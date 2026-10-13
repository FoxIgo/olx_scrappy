from __future__ import annotations

import pytest

from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.offer import OfferStatus, Price
from scrappy.domain.shared import FetchOutcome
from scrappy.infrastructure.scraping.sources.olx_pl.html_state import (
    StateParseError,
    extract_state,
    parse_search_state,
    search_result_from_html,
)
from scrappy.infrastructure.scraping.sources.olx_pl.mapper import map_api_offer, map_state_ad

from .conftest import SEARCH_URL, fixture_json, fixture_text, make_page


def test_extract_state_decodes_double_encoded_json() -> None:
    state = extract_state(fixture_text("search_results.html"))
    assert "listing" in state


def test_parse_search_state_totals_and_next() -> None:
    parsed = parse_search_state(fixture_text("search_results.html"))
    assert len(parsed.items) == 5
    assert parsed.total_elements == 173
    assert parsed.visible_total == 173
    assert parsed.next_href is not None
    assert parsed.next_href.startswith("https://www.olx.pl/api/v1/offers?offset=40&limit=40")


def test_search_result_from_html_maps_ads() -> None:
    raw = make_page(fixture_text("search_results.html"), url=SEARCH_URL, content_type="text/html")

    result = search_result_from_html(raw, PageRef.first(SEARCH_URL))

    assert result.outcome is FetchOutcome.OK
    assert len(result.observations) == 5
    assert result.rejections == ()
    assert result.total_results == 173
    assert result.next_page is not None
    assert result.next_page.number == 2
    first = result.observations[0]
    assert first.offer_id.external_id == "1098526767"
    assert first.price == Price.fixed("1300", "PLN")
    assert first.location == "Bestwina, Śląskie"
    assert first.promoted is True
    assert first.status is OfferStatus.ACTIVE
    assert first.seller is not None
    assert first.seller.external_id == "24901353"
    assert result.observations[1].price == Price.fixed("1400", "PLN", negotiable=True)


def test_state_and_api_mapping_agree_on_shared_fields() -> None:
    state_ads = parse_search_state(fixture_text("search_results.html")).items
    api_items = fixture_json("api_search_page1.json")["data"]
    for state_ad, api_item in zip(state_ads, api_items, strict=True):
        from_state = map_state_ad(state_ad)
        from_api = map_api_offer(api_item)
        assert from_state.offer_id == from_api.offer_id
        assert from_state.title == from_api.title
        assert from_state.price == from_api.price
        assert from_state.location == from_api.location
        assert from_state.posted_at == from_api.posted_at
        assert from_state.refreshed_at == from_api.refreshed_at
        assert from_state.params == from_api.params
        assert from_state.seller == from_api.seller
        assert from_state.status == from_api.status
        assert from_state.has_delivery == from_api.has_delivery
        assert from_state.image_urls == from_api.image_urls
        assert from_state.thumbnail_url == from_api.thumbnail_url


def test_state_exchange_and_free_flags() -> None:
    ads = parse_search_state(fixture_text("search_results.html")).items
    exchange = {**ads[0], "price": {**ads[0]["price"], "exchange": True}}
    free = {**ads[0], "price": {**ads[0]["price"], "free": True}}
    assert map_state_ad(exchange).price == Price.exchange()
    assert map_state_ad(free).price == Price.free()


def test_html_without_state_is_blocked() -> None:
    raw = make_page("<html><body>captcha?</body></html>", content_type="text/html")
    result = search_result_from_html(raw, PageRef.first(SEARCH_URL))
    assert result.outcome is FetchOutcome.BLOCKED


def test_html_403_is_blocked() -> None:
    raw = make_page("x", 403, content_type="text/html")
    assert search_result_from_html(raw, PageRef.first(SEARCH_URL)).outcome is FetchOutcome.BLOCKED


def test_broken_state_is_reported_not_raised() -> None:
    raw = make_page(
        '<script>window.__PRERENDERED_STATE__= "{oops"</script>', content_type="text/html"
    )
    assert search_result_from_html(raw, PageRef.first(SEARCH_URL)).outcome is FetchOutcome.BLOCKED


def test_extract_state_errors() -> None:
    with pytest.raises(StateParseError):
        extract_state("<html></html>")
    with pytest.raises(StateParseError):
        extract_state('window.__PRERENDERED_STATE__ = "[1]"')
    with pytest.raises(StateParseError):
        parse_search_state('window.__PRERENDERED_STATE__ = "{}"')

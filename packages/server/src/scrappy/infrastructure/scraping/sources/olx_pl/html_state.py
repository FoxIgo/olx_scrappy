"""Fallback: search results from the embedded ``window.__PRERENDERED_STATE__`` (spike section 2).

Tested but not wired by default (the JSON API is the primary path). The state is a
**double-encoded** JSON document: ``window.__PRERENDERED_STATE__= "<json string literal>"``.
Ads are camelCase (:class:`StateAd`) and map with the same semantics as the API items.
``links.next`` in the state points at the *API* URL, so the next cursor works with the API
source as well.
"""

from __future__ import annotations

import json
from typing import Any

from scrappy.application.ports.listing_source import PageRef, SearchPageResult
from scrappy.domain.shared import FetchOutcome
from scrappy.infrastructure.scraping.engines.base import RawPage

from .classifier import PageKind, classify_html, retry_after_of
from .mapper import map_state_ad
from .search_page import ParsedSearchPage, assemble_search_result

_MARKER = "window.__PRERENDERED_STATE__"


class StateParseError(ValueError):
    """The page has no (parseable) embedded state."""


def extract_state(html: str) -> dict[str, Any]:
    start = html.find(_MARKER)
    if start < 0:
        raise StateParseError("window.__PRERENDERED_STATE__ not found")
    pos = html.find("=", start + len(_MARKER))
    if pos < 0:
        raise StateParseError("no assignment after __PRERENDERED_STATE__")
    pos += 1
    while pos < len(html) and html[pos].isspace():
        pos += 1
    try:
        literal, _ = json.JSONDecoder().raw_decode(html, pos)
        state = json.loads(literal) if isinstance(literal, str) else literal
    except ValueError as exc:
        raise StateParseError(f"cannot decode __PRERENDERED_STATE__: {exc}") from exc
    if not isinstance(state, dict):
        raise StateParseError("__PRERENDERED_STATE__ is not an object")
    return state  # pyright: ignore[reportUnknownVariableType]


def parse_search_state(html: str) -> ParsedSearchPage:
    state = extract_state(html)
    try:
        listing = state["listing"]["listing"]
        ads = listing["ads"]
    except (KeyError, TypeError) as exc:
        raise StateParseError("state has no listing.listing.ads") from exc
    if not isinstance(ads, list):
        raise StateParseError("listing.listing.ads is not a list")
    links = listing.get("links") or {}
    next_href = links.get("next")
    if isinstance(next_href, dict):
        next_href = next_href.get("href")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    return ParsedSearchPage(
        items=ads,  # pyright: ignore[reportUnknownArgumentType]
        total_elements=_int_or_none(listing.get("totalElements")),
        visible_total=_int_or_none(listing.get("visibleElements")),
        next_href=next_href if isinstance(next_href, str) else None,
    )


def search_result_from_html(
    raw: RawPage, page: PageRef, *, require_price: bool = True
) -> SearchPageResult:
    """Classify a search HTML page and map its embedded ads (never raises for bad pages)."""
    verdict = classify_html(raw)
    if verdict.kind is not PageKind.OK:
        return SearchPageResult.failed(
            verdict.fetch_outcome,
            verdict.message,
            retry_after=retry_after_of(raw),
            raw_ref=raw.archive_ref,
        )
    try:
        parsed = parse_search_state(raw.body)
    except StateParseError as exc:
        return SearchPageResult.failed(FetchOutcome.BLOCKED, str(exc), raw_ref=raw.archive_ref)
    return assemble_search_result(
        parsed, page=page, mapper=map_state_ad, require_price=require_price, raw_ref=raw.archive_ref
    )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None

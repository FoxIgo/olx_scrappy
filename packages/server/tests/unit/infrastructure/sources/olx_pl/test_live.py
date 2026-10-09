"""Opt-in live check (``pytest -m live``): one real search page through the engine factory."""

from __future__ import annotations

import pytest

from scrappy.application.ports.listing_source import PageRef
from scrappy.domain.shared import FetchOutcome
from scrappy.infrastructure.scraping.engines.factory import build_fetcher
from scrappy.infrastructure.scraping.sources.olx_pl.source import OlxPlListingSource

from .conftest import SEARCH_URL


@pytest.mark.live
async def test_olx_pl_one_real_search_page() -> None:
    fetcher = build_fetcher(
        {"engine": "curl_cffi", "rate_limit": "1/3s", "jitter": 0.3, "retries": 1}
    )
    try:
        source = OlxPlListingSource(fetcher, page_size=10)
        result = await source.fetch_search_page(PageRef.first(SEARCH_URL))
    finally:
        await fetcher.aclose()

    assert result.outcome is FetchOutcome.OK, result.message
    assert result.observations or result.rejections
    assert all(o.is_detail_complete for o in result.observations)
    assert result.total_results is not None

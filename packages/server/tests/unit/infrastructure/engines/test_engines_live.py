from __future__ import annotations

import json

import pytest

from scrappy.infrastructure.scraping.engines.base import FetchRequest
from scrappy.infrastructure.scraping.engines.curl_cffi_fetcher import CurlCffiFetcher


@pytest.mark.live
async def test_olx_api_via_curl_cffi() -> None:
    async with CurlCffiFetcher(impersonate="chrome") as fetcher:
        page = await fetcher.fetch(
            FetchRequest("https://www.olx.pl/api/v1/offers/?limit=1&query=laptop")
        )
    assert page.status == 200
    assert "json" in page.content_type
    assert "data" in json.loads(page.body)

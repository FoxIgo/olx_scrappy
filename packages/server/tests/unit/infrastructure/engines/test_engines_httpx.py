from __future__ import annotations

import httpx
import pytest

from scrappy.infrastructure.scraping.engines.base import FetchRequest, FetchTransportError
from scrappy.infrastructure.scraping.engines.httpx_fetcher import HttpxFetcher


async def test_returns_page_for_any_status() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            404, json={"error": "x"}, headers={"X-Thing": "1", "Content-Type": "application/json"}
        )

    async with HttpxFetcher(transport=httpx.MockTransport(handler)) as fetcher:
        page = await fetcher.fetch(
            FetchRequest("https://api.test/v1/x", params={"q": "a b"}, headers={"X-A": "b"})
        )
    assert page.status == 404
    assert page.engine == "httpx"
    assert page.headers["x-thing"] == "1"
    assert page.content_type.startswith("application/json")
    assert '"error"' in page.body
    assert page.final_url.startswith("https://api.test/v1/x?q=a")
    assert seen[0].headers["x-a"] == "b"


async def test_transport_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    fetcher = HttpxFetcher(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchTransportError):
        await fetcher.fetch(FetchRequest("https://api.test/"))
    await fetcher.aclose()

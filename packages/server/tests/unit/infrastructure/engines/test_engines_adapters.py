from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from curl_cffi.requests.exceptions import Timeout

from scrappy.infrastructure.scraping.engines import scrapling_browser_fetcher as browser
from scrappy.infrastructure.scraping.engines.base import (
    FetchEngineUnavailable,
    FetchRequest,
    FetchTransportError,
    PageFetcher,
)
from scrappy.infrastructure.scraping.engines.curl_cffi_fetcher import CurlCffiFetcher
from scrappy.infrastructure.scraping.engines.scrapling_fetcher import (
    ScraplingFetcher,
    response_to_raw_page,
)


class FakeSession:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, Any] = {}
        self.closed = False

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.kwargs = {"method": method, "url": url, **kwargs}
        if self.error:
            raise self.error
        return self.response

    async def close(self) -> None:
        self.closed = True


def test_curl_cffi_defaults_and_protocol() -> None:
    fetcher = CurlCffiFetcher()
    assert fetcher.impersonate == "chrome"
    assert isinstance(fetcher, PageFetcher)


async def test_curl_cffi_maps_response() -> None:
    resp = SimpleNamespace(
        url="https://x.test/final",
        status_code=403,
        headers={"Content-Type": "text/html", "Server": "CloudFront"},
        text="blocked",
    )
    session = FakeSession(resp)
    fetcher = CurlCffiFetcher(session=session)
    page = await fetcher.fetch(FetchRequest("https://x.test/", params={"a": "1"}))
    assert page.status == 403
    assert page.final_url == "https://x.test/final"
    assert page.headers["server"] == "CloudFront"
    assert page.content_type == "text/html"
    assert page.engine == "curl_cffi"
    assert session.kwargs["params"] == {"a": "1"}
    await fetcher.aclose()
    assert session.closed


async def test_curl_cffi_maps_transport_errors() -> None:
    fetcher = CurlCffiFetcher(session=FakeSession(error=Timeout("slow")))
    with pytest.raises(FetchTransportError):
        await fetcher.fetch(FetchRequest("https://x.test/"))


def test_scrapling_response_conversion() -> None:
    resp = SimpleNamespace(
        url="https://x.test/",
        status=200,
        headers={"Content-Type": "application/json"},
        body=b"{}",
        encoding="utf-8",
    )
    page = response_to_raw_page(
        resp, req=FetchRequest("https://x.test/"), elapsed=0.5, engine="scrapling"
    )
    assert (page.status, page.body, page.content_type) == (200, "{}", "application/json")


async def test_scrapling_maps_errors() -> None:
    fetcher = ScraplingFetcher()

    class Boom:
        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("down")

    fetcher._session = Boom()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(FetchTransportError):
        await fetcher.fetch(FetchRequest("https://x.test/"))


def test_browser_adapter_requires_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(name: str) -> Any:
        raise ImportError("no playwright")

    monkeypatch.setattr(browser.importlib, "import_module", fail)
    with pytest.raises(FetchEngineUnavailable, match="browser"):
        browser.ScraplingBrowserFetcher(mode="stealthy")


def test_browser_adapter_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        browser.ScraplingBrowserFetcher(mode="nope")  # type: ignore[arg-type]

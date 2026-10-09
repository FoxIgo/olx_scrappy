from __future__ import annotations

import pytest

from scrappy.infrastructure.scraping.engines.base import FetchRequest, RawPage


def make_page(
    status: int = 200,
    body: str = "<html>ok</html>",
    *,
    url: str = "https://example.com/a",
    headers: dict[str, str] | None = None,
    content_type: str = "text/html",
    engine: str = "fake",
) -> RawPage:
    return RawPage(
        url=url,
        final_url=url,
        status=status,
        headers=headers or {},
        content_type=content_type,
        body=body,
        elapsed=0.01,
        engine=engine,
    )


class FakeFetcher:
    """Replays scripted results (RawPage or Exception); repeats the last one when exhausted."""

    def __init__(self, *results: RawPage | Exception, name: str = "fake") -> None:
        self.results = list(results) or [make_page()]
        self.name = name
        self.calls: list[FetchRequest] = []
        self.closed = False

    async def fetch(self, req: FetchRequest) -> RawPage:
        self.calls.append(req)
        idx = min(len(self.calls) - 1, len(self.results) - 1)
        item = self.results[idx]
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self) -> None:
        self.closed = True


class FakeClock:
    """Deterministic clock whose sleep() advances time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FixedRng:
    """uniform(a, b) returns a + fraction * (b - a)."""

    def __init__(self, fraction: float = 0.0) -> None:
        self.fraction = fraction

    def uniform(self, a: float, b: float) -> float:
        return a + self.fraction * (b - a)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()

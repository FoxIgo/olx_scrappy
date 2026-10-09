"""Browser-based Scrapling fetchers (StealthyFetcher / DynamicFetcher).

Needs the optional ``browser`` extra (``uv sync --extra browser`` plus browser install).
Imports are lazy: constructing the adapter without the extra raises
``FetchEngineUnavailable`` with install instructions. Uses the sync API via
``asyncio.to_thread``. Not exercised by the automated tests (no browsers installed).
"""

from __future__ import annotations

import asyncio
import importlib
import time
from typing import Any, Literal

from scrappy.infrastructure.scraping.engines.base import (
    FetchEngineUnavailable,
    FetcherBase,
    FetchRequest,
    FetchTransportError,
    RawPage,
)
from scrappy.infrastructure.scraping.engines.scrapling_fetcher import response_to_raw_page

BrowserMode = Literal["stealthy", "dynamic"]
_CLASS_NAMES = {"stealthy": "StealthyFetcher", "dynamic": "DynamicFetcher"}


def _load_fetcher_class(mode: BrowserMode) -> Any:
    try:
        fetchers = importlib.import_module("scrapling.fetchers")
        return getattr(fetchers, _CLASS_NAMES[mode])
    except (ImportError, AttributeError) as exc:
        raise FetchEngineUnavailable(
            f"Scrapling {mode} engine needs the optional browser extra: "
            "run `uv sync --extra browser` and install the browsers "
            f"(original error: {exc})"
        ) from exc


class ScraplingBrowserFetcher(FetcherBase):
    def __init__(self, *, mode: BrowserMode = "stealthy", headless: bool = True) -> None:
        if mode not in _CLASS_NAMES:
            raise ValueError(f"unknown browser mode: {mode!r}")
        self.mode = mode
        self.name = f"scrapling_{mode}"
        self._headless = headless
        self._cls = _load_fetcher_class(mode)  # fail fast and clearly

    def _fetch_sync(self, req: FetchRequest) -> Any:
        kwargs: dict[str, Any] = {
            "headless": self._headless,
            "timeout": int(req.timeout * 1000),  # browsers take milliseconds
        }
        if req.wait_for:
            kwargs["wait_selector"] = req.wait_for
        if req.headers:
            kwargs["extra_headers"] = dict(req.headers)
        return self._cls.fetch(req.url, **kwargs)

    async def fetch(self, req: FetchRequest) -> RawPage:
        started = time.perf_counter()
        try:
            resp = await asyncio.to_thread(self._fetch_sync, req)
        except Exception as exc:
            raise FetchTransportError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        return response_to_raw_page(
            resp, req=req, elapsed=time.perf_counter() - started, engine=self.name
        )

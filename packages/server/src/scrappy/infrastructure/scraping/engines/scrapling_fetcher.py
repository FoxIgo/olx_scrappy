"""Scrapling adapters.

``ScraplingFetcher`` uses Scrapling's async HTTP session (``FetcherSession``, itself
curl_cffi based) from the core dependency; used as a library only (ADR 0004 note 2).
Browser fetchers live in ``scrapling_browser_fetcher.py`` (optional ``browser`` extra).
"""

from __future__ import annotations

import time
from typing import Any

from scrappy.infrastructure.scraping.engines.base import (
    FetchEngineUnavailable,
    FetcherBase,
    FetchError,
    FetchRequest,
    FetchTransportError,
    RawPage,
)


def response_to_raw_page(resp: Any, *, req: FetchRequest, elapsed: float, engine: str) -> RawPage:
    """Convert a Scrapling ``Response`` into a RawPage."""
    headers = {str(k).lower(): str(v) for k, v in dict(resp.headers).items()}
    raw = resp.body
    if isinstance(raw, bytes):
        body = raw.decode(getattr(resp, "encoding", None) or "utf-8", errors="replace")
    else:
        body = str(raw)
    return RawPage(
        url=req.url,
        final_url=str(resp.url),
        status=int(resp.status),
        headers=headers,
        content_type=headers.get("content-type", ""),
        body=body,
        elapsed=elapsed,
        engine=engine,
    )


class ScraplingFetcher(FetcherBase):
    name = "scrapling"

    def __init__(self, *, impersonate: str = "chrome", stealthy_headers: bool = True) -> None:
        self.impersonate = impersonate
        self._stealthy_headers = stealthy_headers
        self._manager: Any | None = None
        self._session: Any | None = None

    async def _get_session(self) -> Any:
        if self._session is None:
            # Lazy: in scrapling 0.4.x even the HTTP fetcher imports playwright at import time,
            # so it only loads when the `browser` extra is installed.
            try:
                from scrapling.fetchers import FetcherSession
            except ImportError as exc:
                raise FetchEngineUnavailable(
                    "Scrapling's HTTP fetcher needs the optional browser extra "
                    f"(`uv sync --extra browser`); original error: {exc}"
                ) from exc
            # retries=1: retrying is the job of RetryingFetcher, not of the engine.
            self._manager = FetcherSession(
                impersonate=self.impersonate,  # type: ignore[arg-type]
                stealthy_headers=self._stealthy_headers,
                retries=1,
            )
            self._session = await self._manager.__aenter__()
        return self._session

    async def fetch(self, req: FetchRequest) -> RawPage:
        method = req.method.lower()
        if method not in ("get", "post", "put", "delete"):
            raise FetchError(f"scrapling: unsupported method {req.method}")
        session = await self._get_session()
        started = time.perf_counter()
        try:
            resp = await getattr(session, method)(
                req.url,
                params=dict(req.params) or None,
                headers=dict(req.headers) or None,
                timeout=req.timeout,
            )
        except Exception as exc:  # scrapling/curl_cffi raise assorted exception types
            raise FetchTransportError(f"scrapling: {type(exc).__name__}: {exc}") from exc
        return response_to_raw_page(
            resp, req=req, elapsed=time.perf_counter() - started, engine=self.name
        )

    async def aclose(self) -> None:
        if self._manager is not None:
            await self._manager.__aexit__(None, None, None)
            self._manager = None
            self._session = None

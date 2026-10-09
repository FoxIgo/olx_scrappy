"""httpx adapter. Meant for official APIs; OLX/CloudFront rejects its TLS fingerprint."""

from __future__ import annotations

import time

import httpx

from scrappy.infrastructure.scraping.engines.base import (
    FetcherBase,
    FetchRequest,
    FetchTransportError,
    RawPage,
)


class HttpxFetcher(FetcherBase):
    name = "httpx"

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        follow_redirects: bool = True,
    ) -> None:
        self._client = httpx.AsyncClient(
            headers=headers,
            transport=transport,
            follow_redirects=follow_redirects,
        )

    async def fetch(self, req: FetchRequest) -> RawPage:
        started = time.perf_counter()
        try:
            resp = await self._client.request(
                req.method,
                req.url,
                params=dict(req.params) or None,
                headers=dict(req.headers) or None,
                timeout=req.timeout,
            )
        except httpx.HTTPError as exc:
            raise FetchTransportError(f"httpx: {type(exc).__name__}: {exc}") from exc
        return RawPage(
            url=req.url,
            final_url=str(resp.url),
            status=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            content_type=resp.headers.get("content-type", ""),
            body=resp.text,
            elapsed=time.perf_counter() - started,
            engine=self.name,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

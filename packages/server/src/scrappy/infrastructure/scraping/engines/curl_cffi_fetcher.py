"""curl_cffi adapter with browser TLS impersonation (the default engine for olx.pl, R16)."""

from __future__ import annotations

import time
from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from scrappy.infrastructure.scraping.engines.base import (
    FetcherBase,
    FetchRequest,
    FetchTransportError,
    RawPage,
)


class CurlCffiFetcher(FetcherBase):
    name = "curl_cffi"

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        headers: dict[str, str] | None = None,
        session: Any | None = None,
    ) -> None:
        self.impersonate = impersonate
        self._default_headers = dict(headers or {})
        self._session: Any | None = session

    def _get_session(self) -> Any:
        if self._session is None:
            self._session = AsyncSession(impersonate=self.impersonate)  # type: ignore[arg-type]
        return self._session

    async def fetch(self, req: FetchRequest) -> RawPage:
        session = self._get_session()
        started = time.perf_counter()
        try:
            resp = await session.request(
                req.method,
                req.url,
                params=dict(req.params) or None,
                headers={**self._default_headers, **req.headers} or None,
                timeout=req.timeout,
                allow_redirects=True,
            )
        except RequestException as exc:
            raise FetchTransportError(f"curl_cffi: {type(exc).__name__}: {exc}") from exc
        headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}
        return RawPage(
            url=req.url,
            final_url=str(resp.url),
            status=int(resp.status_code),
            headers=headers,
            content_type=headers.get("content-type", ""),
            body=resp.text,
            elapsed=time.perf_counter() - started,
            engine=self.name,
        )

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

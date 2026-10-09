"""Cross-cutting fetcher decorators (ADR 0004 sections 4, 7). Each is itself a PageFetcher."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import gzip
import hashlib
import json
import os
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from scrappy.infrastructure.scraping.engines.base import (
    Classifier,
    EngineFetchOutcome,
    FetcherBase,
    FetchRequest,
    FetchTransportError,
    PageFetcher,
    RawPage,
    classify_generic,
)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class SupportsUniform(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class _Wrapping(FetcherBase):
    """Shared plumbing: owns an inner fetcher and closes it."""

    def __init__(self, inner: PageFetcher) -> None:
        self._inner = inner

    async def fetch(self, req: FetchRequest) -> RawPage:
        return await self._inner.fetch(req)

    async def aclose(self) -> None:
        await self._inner.aclose()


# ------------------------------------------------------------------ politeness


class HostThrottle:
    """Per-host concurrency limit plus a minimum, jittered interval between request starts.

    Shareable between several fetchers so a fallback chain is throttled as one.
    """

    def __init__(
        self,
        *,
        concurrency: int = 1,
        min_interval: float = 0.0,
        jitter: float = 0.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        rng: SupportsUniform | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if min_interval < 0 or jitter < 0:
            raise ValueError("min_interval and jitter must be >= 0")
        self.concurrency = concurrency
        self.min_interval = min_interval
        self.jitter = jitter
        self._sleep = sleep
        self._clock = clock
        self._rng: SupportsUniform = rng or random.Random()
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._next_allowed: dict[str, float] = {}

    def _semaphore(self, host: str) -> asyncio.Semaphore:
        sem = self._semaphores.get(host)
        if sem is None:
            sem = self._semaphores[host] = asyncio.Semaphore(self.concurrency)
        return sem

    async def acquire(self, host: str) -> asyncio.Semaphore:
        """Wait for a slot; the caller must release the returned semaphore."""
        sem = self._semaphore(host)
        await sem.acquire()
        try:
            # Reserve the next slot before awaiting so concurrent waiters can't share it.
            now = self._clock()
            start = max(now, self._next_allowed.get(host, now))
            gap = self.min_interval + (self._rng.uniform(0, self.jitter) if self.jitter else 0.0)
            self._next_allowed[host] = start + gap
            if start > now:
                await self._sleep(start - now)
        except BaseException:
            sem.release()
            raise
        return sem


class PolitePerHostFetcher(_Wrapping):
    def __init__(
        self,
        inner: PageFetcher,
        *,
        throttle: HostThrottle | None = None,
        concurrency: int = 1,
        min_interval: float = 0.0,
        jitter: float = 0.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        rng: SupportsUniform | None = None,
    ) -> None:
        super().__init__(inner)
        self.throttle = throttle or HostThrottle(
            concurrency=concurrency,
            min_interval=min_interval,
            jitter=jitter,
            sleep=sleep,
            clock=clock,
            rng=rng,
        )

    async def fetch(self, req: FetchRequest) -> RawPage:
        sem = await self.throttle.acquire(host_of(req.url))
        try:
            return await self._inner.fetch(req)
        finally:
            sem.release()


# ------------------------------------------------------------------ retries


def parse_retry_after(value: str | None, *, now: dt.datetime | None = None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or HTTP date); None if unusable."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    current = now or dt.datetime.now(dt.UTC)
    return max(0.0, (when - current).total_seconds())


class RetryingFetcher(_Wrapping):
    """Retries transport errors, TRANSIENT outcomes and HTTP 429. Never 403/404."""

    def __init__(
        self,
        inner: PageFetcher,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.25,
        max_retry_after: float = 300.0,
        classifier: Classifier = classify_generic,
        sleep: Sleep = asyncio.sleep,
        rng: SupportsUniform | None = None,
    ) -> None:
        super().__init__(inner)
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.max_retry_after = max_retry_after
        self._classifier = classifier
        self._sleep = sleep
        self._rng: SupportsUniform = rng or random.Random()

    def _should_retry(self, page: RawPage) -> bool:
        if page.status == 429:
            return True
        return self._classifier(page) is EngineFetchOutcome.TRANSIENT

    def _delay(self, attempt: int, page: RawPage | None) -> float:
        if page is not None:
            retry_after = parse_retry_after(page.headers.get("retry-after"))
            if retry_after is not None:
                return min(retry_after, self.max_retry_after)
        backoff = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return backoff * (1 + self._rng.uniform(0, self.jitter))

    async def fetch(self, req: FetchRequest) -> RawPage:
        attempt = 1
        while True:
            page: RawPage | None = None
            try:
                page = await self._inner.fetch(req)
            except FetchTransportError:
                if attempt >= self.max_attempts:
                    raise
            else:
                if not self._should_retry(page) or attempt >= self.max_attempts:
                    return page
            await self._sleep(self._delay(attempt, page))
            attempt += 1


# ------------------------------------------------------------------ fallback


class FallbackFetcher(_Wrapping):
    """Ordered engines; escalates to the next only when the classifier says BLOCKED."""

    def __init__(
        self,
        fetchers: Sequence[PageFetcher],
        *,
        classifier: Classifier = classify_generic,
    ) -> None:
        if not fetchers:
            raise ValueError("FallbackFetcher needs at least one fetcher")
        super().__init__(fetchers[0])
        self._fetchers = list(fetchers)
        self._classifier = classifier

    async def fetch(self, req: FetchRequest) -> RawPage:
        page: RawPage | None = None
        for fetcher in self._fetchers:
            page = await fetcher.fetch(req)
            if self._classifier(page) is not EngineFetchOutcome.BLOCKED:
                return page
        assert page is not None
        return page

    async def aclose(self) -> None:
        for fetcher in self._fetchers:
            await fetcher.aclose()


# ------------------------------------------------------------------ archiving


class ArchiveWriter(Protocol):
    """Stores bytes under a relative key and returns a reference to the stored object."""

    def write(self, key: str, data: bytes) -> str: ...


class FileArchiveWriter:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return str(path)


def url_digest(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()


class ArchivingFetcher(_Wrapping):
    """Writes OK pages as gzip to ``<date>/<host>/<sha1(final_url)>.<ext>.gz``; sets archive_ref."""

    def __init__(
        self,
        inner: PageFetcher,
        writer: ArchiveWriter,
        *,
        classifier: Classifier = classify_generic,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        super().__init__(inner)
        self._writer = writer
        self._classifier = classifier
        self._now = now

    def key_for(self, page: RawPage) -> str:
        ext = "json" if "json" in page.content_type.lower() else "html"
        day = self._now().strftime("%Y-%m-%d")
        # final_url includes the query string, so paginated API calls that pass
        # offset/limit as params don't collide on the same key.
        return f"{day}/{host_of(page.url)}/{url_digest(page.final_url or page.url)}.{ext}.gz"

    async def fetch(self, req: FetchRequest) -> RawPage:
        page = await self._inner.fetch(req)
        if self._classifier(page) is not EngineFetchOutcome.OK:
            return page
        data = gzip.compress(page.body.encode("utf-8"), mtime=0)
        ref = await asyncio.to_thread(self._writer.write, self.key_for(page), data)
        return dataclasses.replace(page, archive_ref=ref)


# ------------------------------------------------------------------ dev cache


class CachingFetcher(_Wrapping):
    """Dev only: on-disk cache of OK pages keyed by method+url+params, with a TTL."""

    def __init__(
        self,
        inner: PageFetcher,
        cache_dir: Path | str,
        *,
        ttl: float = 3600.0,
        classifier: Classifier = classify_generic,
        clock: Clock = time.time,
    ) -> None:
        super().__init__(inner)
        self._dir = Path(cache_dir)
        self._ttl = ttl
        self._classifier = classifier
        self._clock = clock

    @staticmethod
    def cache_key(req: FetchRequest) -> str:
        raw = json.dumps([req.method, req.url, sorted(req.params.items())], ensure_ascii=True)
        return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()

    def _path(self, req: FetchRequest) -> Path:
        return self._dir / f"{self.cache_key(req)}.json"

    def _load(self, req: FetchRequest) -> RawPage | None:
        path = self._path(req)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if self._clock() - float(doc["stored_at"]) > self._ttl:
                return None
            return RawPage(**doc["page"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _store(self, req: FetchRequest, page: RawPage) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        doc = {"stored_at": self._clock(), "page": dataclasses.asdict(page)}
        path = self._path(req)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.replace(tmp, path)

    async def fetch(self, req: FetchRequest) -> RawPage:
        cached = await asyncio.to_thread(self._load, req)
        if cached is not None:
            return cached
        page = await self._inner.fetch(req)
        if self._classifier(page) is EngineFetchOutcome.OK:
            await asyncio.to_thread(self._store, req, page)
        return page

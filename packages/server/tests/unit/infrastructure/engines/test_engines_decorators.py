from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import random
from pathlib import Path

import pytest

from scrappy.infrastructure.scraping.engines.base import (
    EngineFetchOutcome,
    FetchRequest,
    FetchTransportError,
    PageFetcher,
    RawPage,
)
from scrappy.infrastructure.scraping.engines.decorators import (
    ArchivingFetcher,
    CachingFetcher,
    FallbackFetcher,
    FileArchiveWriter,
    PolitePerHostFetcher,
    RetryingFetcher,
    parse_retry_after,
    url_digest,
)

from .conftest import FakeClock, FakeFetcher, FixedRng, make_page

REQ = FetchRequest("https://example.com/a")


# ------------------------------------------------------------------ polite


async def test_polite_spaces_requests_per_host(clock: FakeClock) -> None:
    polite = PolitePerHostFetcher(
        FakeFetcher(), min_interval=3.0, sleep=clock.sleep, clock=clock, rng=FixedRng()
    )
    starts: list[float] = []
    for _ in range(3):
        await polite.fetch(REQ)
        starts.append(clock())
    assert starts == [1000.0, 1003.0, 1006.0]
    assert clock.sleeps == [3.0, 3.0]


async def test_polite_jitter_within_bounds(clock: FakeClock) -> None:
    polite = PolitePerHostFetcher(
        FakeFetcher(),
        min_interval=2.0,
        jitter=1.0,
        sleep=clock.sleep,
        clock=clock,
        rng=random.Random(42),
    )
    for _ in range(30):
        await polite.fetch(REQ)
    assert len(clock.sleeps) == 29
    assert all(2.0 <= s <= 3.0 for s in clock.sleeps)
    assert len(set(clock.sleeps)) > 1  # actually jittered


async def test_polite_jitter_uses_injected_rng(clock: FakeClock) -> None:
    polite = PolitePerHostFetcher(
        FakeFetcher(),
        min_interval=2.0,
        jitter=1.0,
        sleep=clock.sleep,
        clock=clock,
        rng=FixedRng(0.5),
    )
    await polite.fetch(REQ)
    await polite.fetch(REQ)
    assert clock.sleeps == [2.5]


async def test_polite_hosts_are_isolated(clock: FakeClock) -> None:
    polite = PolitePerHostFetcher(
        FakeFetcher(), min_interval=5.0, sleep=clock.sleep, clock=clock, rng=FixedRng()
    )
    await polite.fetch(FetchRequest("https://a.example/x"))
    await polite.fetch(FetchRequest("https://b.example/x"))
    assert clock.sleeps == []
    await polite.fetch(FetchRequest("https://a.example/y"))
    assert clock.sleeps == [5.0]


async def test_polite_concurrency_limit_per_host() -> None:
    active = {"n": 0, "max": 0}

    class Slow:
        async def fetch(self, req: FetchRequest) -> RawPage:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await asyncio.sleep(0.01)
            active["n"] -= 1
            return make_page()

        async def aclose(self) -> None: ...

    polite = PolitePerHostFetcher(Slow(), concurrency=2)
    await asyncio.gather(*(polite.fetch(REQ) for _ in range(6)))
    assert active["max"] == 2

    active.update(n=0, max=0)
    # Different hosts do not share the limit.
    await asyncio.gather(*(polite.fetch(FetchRequest(f"https://h{i}.example/")) for i in range(6)))
    assert active["max"] == 6


async def test_polite_releases_slot_on_error(clock: FakeClock) -> None:
    inner = FakeFetcher(FetchTransportError("x"), make_page())
    polite = PolitePerHostFetcher(inner, concurrency=1, sleep=clock.sleep, clock=clock)
    with pytest.raises(FetchTransportError):
        await polite.fetch(REQ)
    assert (await polite.fetch(REQ)).status == 200


# ------------------------------------------------------------------ retry


def retrying(
    inner: PageFetcher, clock: FakeClock, *, max_attempts: int = 3, max_retry_after: float = 300.0
) -> RetryingFetcher:
    return RetryingFetcher(
        inner,
        sleep=clock.sleep,
        rng=FixedRng(0.0),
        base_delay=1.0,
        max_attempts=max_attempts,
        max_retry_after=max_retry_after,
    )


async def test_retry_on_transient_with_exponential_backoff(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(503), make_page(500), make_page(200))
    page = await retrying(inner, clock).fetch(REQ)
    assert page.status == 200
    assert len(inner.calls) == 3
    assert clock.sleeps == [1.0, 2.0]


async def test_retry_backoff_jitter_bounds(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(503), make_page(200))
    r = RetryingFetcher(inner, sleep=clock.sleep, rng=FixedRng(1.0), base_delay=4.0, jitter=0.25)
    await r.fetch(REQ)
    assert clock.sleeps == [5.0]


async def test_retry_backoff_capped_and_last_result_returned(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(503))
    r = RetryingFetcher(
        inner, max_attempts=6, sleep=clock.sleep, rng=FixedRng(0.0), base_delay=10, max_delay=25
    )
    page = await r.fetch(REQ)
    assert page.status == 503
    assert clock.sleeps == [10, 20, 25, 25, 25]


async def test_retry_honors_retry_after(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(429, headers={"retry-after": "7"}), make_page(200))
    await retrying(inner, clock).fetch(REQ)
    assert clock.sleeps == [7.0]


async def test_retry_after_is_capped(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(503, headers={"retry-after": "99999"}), make_page(200))
    await retrying(inner, clock, max_retry_after=30).fetch(REQ)
    assert clock.sleeps == [30]


async def test_429_without_retry_after_uses_backoff(clock: FakeClock) -> None:
    inner = FakeFetcher(make_page(429), make_page(200))
    await retrying(inner, clock).fetch(REQ)
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize("status", [403, 404, 200, 400])
async def test_no_retry_on_other_statuses(clock: FakeClock, status: int) -> None:
    inner = FakeFetcher(make_page(status))
    page = await retrying(inner, clock).fetch(REQ)
    assert page.status == status
    assert len(inner.calls) == 1
    assert clock.sleeps == []


async def test_retry_transport_error_then_raise(clock: FakeClock) -> None:
    inner = FakeFetcher(FetchTransportError("down"))
    with pytest.raises(FetchTransportError):
        await retrying(inner, clock, max_attempts=3).fetch(REQ)
    assert len(inner.calls) == 3
    assert len(clock.sleeps) == 2


async def test_retry_transport_error_recovers(clock: FakeClock) -> None:
    inner = FakeFetcher(FetchTransportError("down"), make_page())
    assert (await retrying(inner, clock).fetch(REQ)).status == 200


def test_parse_retry_after() -> None:
    now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after(" 1.5 ") == 1.5
    assert parse_retry_after("Thu, 01 Jan 2026 12:00:30 GMT", now=now) == 30.0
    assert parse_retry_after("Thu, 01 Jan 2026 11:00:00 GMT", now=now) == 0.0
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None


# ------------------------------------------------------------------ fallback


async def test_fallback_escalates_only_on_blocked() -> None:
    a = FakeFetcher(make_page(403))
    b = FakeFetcher(make_page(200, "good", engine="b"))
    page = await FallbackFetcher([a, b]).fetch(REQ)
    assert page.engine == "b"
    assert len(a.calls) == len(b.calls) == 1


@pytest.mark.parametrize("status", [200, 404, 500])
async def test_fallback_does_not_escalate_otherwise(status: int) -> None:
    a = FakeFetcher(make_page(status))
    b = FakeFetcher(make_page(200))
    page = await FallbackFetcher([a, b]).fetch(REQ)
    assert page.status == status
    assert b.calls == []


async def test_fallback_returns_last_when_all_blocked() -> None:
    a = FakeFetcher(make_page(403, "first"))
    b = FakeFetcher(make_page(429, "last"))
    page = await FallbackFetcher([a, b]).fetch(REQ)
    assert (page.status, page.body) == (429, "last")


async def test_fallback_custom_classifier_and_close() -> None:
    a = FakeFetcher(make_page(200, "captcha"))
    b = FakeFetcher(make_page(200, "fine"))
    fb = FallbackFetcher(
        [a, b],
        classifier=lambda p: (
            EngineFetchOutcome.BLOCKED if "captcha" in p.body else EngineFetchOutcome.OK
        ),
    )
    assert (await fb.fetch(REQ)).body == "fine"
    await fb.aclose()
    assert a.closed
    assert b.closed


async def test_fallback_transport_error_propagates() -> None:
    fb = FallbackFetcher([FakeFetcher(FetchTransportError("x")), FakeFetcher()])
    with pytest.raises(FetchTransportError):
        await fb.fetch(REQ)


def test_fallback_requires_fetchers() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FallbackFetcher([])


# ------------------------------------------------------------------ archiving


class MemoryWriter:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    def write(self, key: str, data: bytes) -> str:
        self.items[key] = data
        return f"mem://{key}"


async def test_archiving_writes_gzip_with_key_and_ref() -> None:
    writer = MemoryWriter()
    now = dt.datetime(2026, 10, 9, 8, 0, tzinfo=dt.UTC)
    url = "https://www.olx.pl/api/v1/offers/?limit=1"
    inner = FakeFetcher(make_page(200, '{"a": "zażółć"}', url=url, content_type="application/json"))
    arch = ArchivingFetcher(inner, writer, now=lambda: now)
    page = await arch.fetch(FetchRequest(url))
    key = f"2026-10-09/www.olx.pl/{url_digest(url)}.json.gz"
    assert page.archive_ref == f"mem://{key}"
    assert gzip.decompress(writer.items[key]).decode() == '{"a": "zażółć"}'


async def test_archiving_html_extension_and_skips_non_ok() -> None:
    writer = MemoryWriter()
    arch = ArchivingFetcher(
        FakeFetcher(make_page(200, "<p>x</p>")), writer, now=lambda: dt.datetime(2026, 1, 2)
    )
    await arch.fetch(REQ)
    assert next(iter(writer.items)).endswith(".html.gz")

    writer2 = MemoryWriter()
    blocked = ArchivingFetcher(FakeFetcher(make_page(403)), writer2)
    page = await blocked.fetch(REQ)
    assert page.archive_ref is None
    assert writer2.items == {}


async def test_file_archive_writer(tmp_path: Path) -> None:
    arch = ArchivingFetcher(FakeFetcher(make_page(200, "hello")), FileArchiveWriter(tmp_path))
    page = await arch.fetch(REQ)
    assert page.archive_ref is not None
    ref = Path(page.archive_ref)
    assert ref.is_relative_to(tmp_path)
    assert gzip.decompress(await asyncio.to_thread(ref.read_bytes)) == b"hello"


# ------------------------------------------------------------------ caching


async def test_cache_hit_miss_and_ttl(tmp_path: Path) -> None:
    now = {"t": 100.0}
    inner = FakeFetcher(make_page(200, "v1"), make_page(200, "v2"))
    cache = CachingFetcher(inner, tmp_path, ttl=60, clock=lambda: now["t"])
    assert (await cache.fetch(REQ)).body == "v1"
    now["t"] = 130.0
    assert (await cache.fetch(REQ)).body == "v1"
    assert len(inner.calls) == 1
    now["t"] = 161.0
    assert (await cache.fetch(REQ)).body == "v2"
    assert len(inner.calls) == 2


async def test_cache_key_includes_params_and_skips_non_ok(tmp_path: Path) -> None:
    inner = FakeFetcher(make_page(200, "one"), make_page(200, "two"), make_page(500, "err"))
    cache = CachingFetcher(inner, tmp_path)
    a = await cache.fetch(FetchRequest("https://x.test/", params={"q": "1"}))
    b = await cache.fetch(FetchRequest("https://x.test/", params={"q": "2"}))
    assert (a.body, b.body) == ("one", "two")
    err_req = FetchRequest("https://x.test/err")
    assert (await cache.fetch(err_req)).status == 500
    assert (await cache.fetch(err_req)).status == 500  # not cached
    assert len(inner.calls) == 4


async def test_cache_param_order_irrelevant(tmp_path: Path) -> None:
    inner = FakeFetcher()
    cache = CachingFetcher(inner, tmp_path)
    await cache.fetch(FetchRequest("https://x.test/", params={"a": "1", "b": "2"}))
    await cache.fetch(FetchRequest("https://x.test/", params={"b": "2", "a": "1"}))
    assert len(inner.calls) == 1


async def test_cache_survives_corrupt_entry(tmp_path: Path) -> None:
    inner = FakeFetcher()
    cache = CachingFetcher(inner, tmp_path)
    (tmp_path / f"{cache.cache_key(REQ)}.json").write_text("{not json")
    assert (await cache.fetch(REQ)).status == 200


# ------------------------------------------------------------------ plumbing


async def test_decorators_are_page_fetchers_and_close_inner() -> None:
    inner = FakeFetcher()
    stack = RetryingFetcher(PolitePerHostFetcher(inner))
    assert isinstance(stack, PageFetcher)
    async with stack:
        pass
    assert inner.closed

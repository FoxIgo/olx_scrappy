from __future__ import annotations

from pathlib import Path

import pytest

from scrappy.infrastructure.scraping.engines.base import FetchEngineUnavailable
from scrappy.infrastructure.scraping.engines.curl_cffi_fetcher import CurlCffiFetcher
from scrappy.infrastructure.scraping.engines.decorators import (
    ArchivingFetcher,
    CachingFetcher,
    FallbackFetcher,
    PolitePerHostFetcher,
    RetryingFetcher,
)
from scrappy.infrastructure.scraping.engines.factory import (
    EngineConfig,
    build_fetcher,
    parse_rate_limit,
)


@pytest.mark.parametrize(
    ("text", "interval"),
    [("1/3s", 3.0), ("2/10s", 5.0), ("1/s", 1.0), ("30/m", 2.0), ("1/2m", 120.0), ("100/h", 36.0)],
)
def test_parse_rate_limit(text: str, interval: float) -> None:
    assert parse_rate_limit(text).min_interval == pytest.approx(interval)


@pytest.mark.parametrize("bad", ["", "fast", "1/3x", "0/3s", "1/0s", "/3s", "1 per 3s"])
def test_parse_rate_limit_rejects(bad: str) -> None:
    with pytest.raises(ValueError, match="rate limit"):
        parse_rate_limit(bad)


def test_builds_olx_stack(tmp_path: Path) -> None:
    fetcher = build_fetcher(
        {
            "engine": "curl_cffi",
            "impersonate": "chrome",
            "rate_limit": "1/3s",
            "concurrency": 1,
            "retries": 3,
            "archive": True,
            "archive_dir": str(tmp_path),
            "enabled": True,  # unknown keys are tolerated
        }
    )
    assert isinstance(fetcher, ArchivingFetcher)
    retrying = fetcher._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(retrying, RetryingFetcher)
    assert retrying.max_attempts == 4
    fallback = retrying._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(fallback, FallbackFetcher)
    polite = fallback._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(polite, PolitePerHostFetcher)
    assert polite.throttle.min_interval == 3.0
    assert polite.throttle.jitter == pytest.approx(0.9)
    engine = polite._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(engine, CurlCffiFetcher)


def test_fallback_chain_shares_throttle_and_cache_is_outermost(tmp_path: Path) -> None:
    fetcher = build_fetcher(
        EngineConfig(engine=["curl_cffi", "httpx"], rate_limit="1/s", cache_dir=str(tmp_path))
    )
    assert isinstance(fetcher, CachingFetcher)
    retrying = fetcher._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(retrying, RetryingFetcher)
    chain = retrying._inner  # pyright: ignore[reportPrivateUsage]
    assert isinstance(chain, FallbackFetcher)
    members = chain._fetchers  # pyright: ignore[reportPrivateUsage]
    throttles = {id(f.throttle) for f in members if isinstance(f, PolitePerHostFetcher)}
    assert len(members) == 2
    assert len(throttles) == 1


def test_unknown_engine() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        build_fetcher({"engine": "nope"})


def test_browser_engine_without_extra_is_clear_or_builds() -> None:
    try:
        build_fetcher({"engine": "scrapling_stealthy"})
    except FetchEngineUnavailable:
        with pytest.raises(FetchEngineUnavailable, match="browser"):
            build_fetcher({"engine": "scrapling_stealthy"})

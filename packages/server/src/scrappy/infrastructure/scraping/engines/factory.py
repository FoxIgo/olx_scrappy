"""Builds the decorator stack for one source from a sources.yaml-shaped config (ADR 0004).

Stack, outermost first::

    Caching (dev, optional) -> Archiving -> Retrying -> Fallback([Polite(engine), ...])

Each engine is wrapped by Polite with one shared per-host throttle, so every real
request (retries and escalations included) obeys the rate limit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from scrappy.infrastructure.scraping.engines.base import PageFetcher
from scrappy.infrastructure.scraping.engines.decorators import (
    ArchiveWriter,
    ArchivingFetcher,
    CachingFetcher,
    FallbackFetcher,
    FileArchiveWriter,
    HostThrottle,
    PolitePerHostFetcher,
    RetryingFetcher,
)

_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0}
_RATE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)?\s*([smh])\s*$")


@dataclass(frozen=True)
class RateLimit:
    requests: float
    per_seconds: float

    @property
    def min_interval(self) -> float:
        return self.per_seconds / self.requests


def parse_rate_limit(text: str) -> RateLimit:
    """Parse '1/3s' (1 request per 3 s), '2/10s', '1/s', '30/m', '100/h'."""
    match = _RATE_RE.match(text)
    if not match:
        raise ValueError(f"invalid rate limit {text!r}; expected e.g. '1/3s'")
    requests = float(match.group(1))
    count = float(match.group(2)) if match.group(2) else 1.0
    per_seconds = count * _UNITS[match.group(3)]
    if requests <= 0 or per_seconds <= 0:
        raise ValueError(f"invalid rate limit {text!r}: values must be positive")
    return RateLimit(requests, per_seconds)


@dataclass(frozen=True)
class EngineConfig:
    engine: str | list[str] = "curl_cffi"
    rate_limit: str | None = None
    jitter: float = 0.3  # fraction of the min interval added at random
    concurrency: int = 1
    retries: int = 3  # retries after the first attempt
    impersonate: str = "chrome"
    timeout_seconds: float = 30.0
    archive: bool = False
    archive_dir: str = "data/raw"
    cache_dir: str | None = None  # dev only
    cache_ttl_seconds: float = 3600.0
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> EngineConfig:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs, extra={k: v for k, v in data.items() if k not in known})

    @property
    def engines(self) -> list[str]:
        return [self.engine] if isinstance(self.engine, str) else list(self.engine)


def build_engine(name: str, config: EngineConfig) -> PageFetcher:
    """Instantiate one raw engine by name (imports are lazy to keep optional deps optional)."""
    if name == "curl_cffi":
        from scrappy.infrastructure.scraping.engines.curl_cffi_fetcher import CurlCffiFetcher

        return CurlCffiFetcher(impersonate=config.impersonate)
    if name == "httpx":
        from scrappy.infrastructure.scraping.engines.httpx_fetcher import HttpxFetcher

        return HttpxFetcher()
    if name == "scrapling":
        from scrappy.infrastructure.scraping.engines.scrapling_fetcher import ScraplingFetcher

        return ScraplingFetcher(impersonate=config.impersonate)
    if name in ("scrapling_stealthy", "scrapling_dynamic"):
        from scrappy.infrastructure.scraping.engines.scrapling_browser_fetcher import (
            ScraplingBrowserFetcher,
        )

        mode = "stealthy" if name.endswith("stealthy") else "dynamic"
        return ScraplingBrowserFetcher(mode=mode)
    raise ValueError(
        f"unknown engine {name!r}; expected curl_cffi | httpx | scrapling | "
        "scrapling_stealthy | scrapling_dynamic"
    )


def build_fetcher(
    config: EngineConfig | Mapping[str, Any],
    *,
    archive_writer: ArchiveWriter | None = None,
) -> PageFetcher:
    cfg = config if isinstance(config, EngineConfig) else EngineConfig.from_mapping(config)
    names = cfg.engines
    if not names:
        raise ValueError("engine list is empty")

    min_interval = parse_rate_limit(cfg.rate_limit).min_interval if cfg.rate_limit else 0.0
    throttle = HostThrottle(
        concurrency=cfg.concurrency,
        min_interval=min_interval,
        jitter=min_interval * cfg.jitter,
    )
    engines = [PolitePerHostFetcher(build_engine(n, cfg), throttle=throttle) for n in names]
    # Uniform shape: a single engine is a one-element fallback chain.
    fetcher: PageFetcher = FallbackFetcher(engines)
    fetcher = RetryingFetcher(fetcher, max_attempts=cfg.retries + 1)
    if cfg.archive:
        fetcher = ArchivingFetcher(fetcher, archive_writer or FileArchiveWriter(cfg.archive_dir))
    if cfg.cache_dir:
        fetcher = CachingFetcher(fetcher, cfg.cache_dir, ttl=cfg.cache_ttl_seconds)
    return fetcher

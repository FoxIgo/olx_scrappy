"""Config-driven pipeline policies (ADR 0006 "trigger policy is config, not code").

Plain values built in ``main.py`` from env/config files; handlers only read them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from scrappy.domain.run import HealthThresholds
from scrappy.domain.shared import InvalidValueError, SourceId


@dataclass(frozen=True, slots=True)
class ExtractionPolicy:
    auto: bool = True
    """``pipeline.extract.auto``: enqueue ExtractOffer as soon as content changes. If False,
    extraction runs only on demand (``RequeueExtractions``)."""
    description_max_chars: int = 4000
    """Descriptions are truncated to this many characters before going to the LLM."""

    def __post_init__(self) -> None:
        if self.description_max_chars < 100:
            raise InvalidValueError("description_max_chars must be >= 100")


@dataclass(frozen=True, slots=True)
class DiscoveryPolicy:
    max_pages: int = 100
    """Safety cap on pages per run; reaching it marks discovery as truncated."""

    def __post_init__(self) -> None:
        if self.max_pages < 1:
            raise InvalidValueError("max_pages must be >= 1")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff for retryable job failures. No jitter: politeness jitter
    belongs to the fetch engines (ADR 0004)."""

    max_attempts: int = 5
    base_delay: timedelta = timedelta(seconds=30)
    max_delay: timedelta = timedelta(hours=1)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise InvalidValueError("max_attempts must be >= 1")

    def retry_at(
        self, attempts: int, now: datetime, hint: timedelta | None = None
    ) -> datetime | None:
        """When to retry after ``attempts`` attempts, or ``None`` when out of attempts.
        A ``hint`` (e.g. Retry-After) is honored when longer than the backoff."""
        if attempts >= self.max_attempts:
            return None
        delay = min(self.max_delay, self.base_delay * (2 ** max(attempts - 1, 0)))
        if hint is not None and hint > delay:
            delay = hint
        return now + delay


@dataclass(frozen=True, slots=True)
class HealthPolicy:
    default: HealthThresholds = field(default_factory=HealthThresholds)
    per_source: Mapping[SourceId, HealthThresholds] = field(
        default_factory=dict[SourceId, HealthThresholds]
    )

    def for_source(self, source: SourceId) -> HealthThresholds:
        return self.per_source.get(source, self.default)


@dataclass(frozen=True, slots=True)
class PipelinePolicy:
    extraction: ExtractionPolicy = field(default_factory=ExtractionPolicy)
    discovery: DiscoveryPolicy = field(default_factory=DiscoveryPolicy)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    health: HealthPolicy = field(default_factory=HealthPolicy)

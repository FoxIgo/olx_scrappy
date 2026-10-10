"""Config-driven pipeline policies (ADR 0006 "trigger policy is config, not code").

Plain values built in ``main.py`` from env/config files; handlers only read them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from scrappy.domain.extraction import ExtractionRetryPolicy
from scrappy.domain.run import HealthThresholds
from scrappy.domain.shared import InvalidValueError, SourceId

ALL_REASONS = "*"


@dataclass(frozen=True, slots=True)
class TieringPolicy:
    """Rules first, LLM only for promising and uncertain offers (ADR 0012)."""

    enabled: bool = False
    """Off: every offer goes to the LLM as before (rule results are still stored when the
    pass runs, as the fast provisional answer)."""
    top_n: int = 25
    """Per scoring strategy: the best ``top_n`` provisional deals go to the LLM."""
    min_coverage: float = 0.5
    """Coverage a provisional score needs to count for ``top_n`` (rule facts are sparser)."""
    escalate: frozenset[str] = frozenset({ALL_REASONS})
    """Rule uncertainty reasons that send an offer to the LLM; ``*`` = every reason."""

    def __post_init__(self) -> None:
        if self.top_n < 0:
            raise InvalidValueError("top_n must be >= 0")
        if not 0 <= self.min_coverage <= 1:
            raise InvalidValueError("min_coverage must be between 0 and 1")

    def escalates(self, reason: str) -> bool:
        return ALL_REASONS in self.escalate or reason in self.escalate


@dataclass(frozen=True, slots=True)
class ExtractionPolicy:
    """The reconciling extractor (ADR 0010). Per-profile tuning lives on the profiles."""

    description_max_chars: int = 4000
    """Descriptions are truncated to this many characters before going to the LLM."""
    retry: ExtractionRetryPolicy = field(default_factory=ExtractionRetryPolicy)
    """Per-offer backoff and parking."""
    reconcile_interval: timedelta = timedelta(seconds=30)
    """Extractor loop: pause between reconcile ticks when there was nothing to do."""
    poll_interval: timedelta = timedelta(seconds=60)
    """Extractor loop: how often open provider batches are polled."""
    sync_lease: timedelta = timedelta(minutes=10)
    """Lease of offers claimed for a sync chunk (a killed extractor loses them this long)."""
    max_items_per_tick: int = 200
    """Sync items per reconcile tick (keeps ticks short so polling and shutdown stay timely)."""
    quota_cooldown: timedelta = timedelta(hours=1)
    """A profile that answered 402 / quota exhausted is skipped this long."""
    health_ttl: timedelta = timedelta(minutes=5)
    """Profile health results are cached this long (failures re-checked after it)."""
    submitting_timeout: timedelta = timedelta(minutes=10)
    """A batch stuck in ``submitting`` longer than this is reconciled with the provider."""
    tiering: TieringPolicy = field(default_factory=TieringPolicy)
    """Rule pass + LLM gate (ADR 0012)."""

    def __post_init__(self) -> None:
        if self.description_max_chars < 100:
            raise InvalidValueError("description_max_chars must be >= 100")
        if self.max_items_per_tick < 1:
            raise InvalidValueError("max_items_per_tick must be >= 1")


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

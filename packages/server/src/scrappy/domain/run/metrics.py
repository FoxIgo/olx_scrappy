"""Per-phase run metrics (ADR 0005 section 3). Immutable; combined with ``+``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from scrappy.domain.extraction import TokenUsage
from scrappy.domain.shared import FetchOutcome


class Phase(StrEnum):
    DISCOVERY = "discovery"
    ENRICHMENT = "enrichment"
    EXTRACTION = "extraction"


def _add_counts[K](a: Mapping[K, int], b: Mapping[K, int]) -> dict[K, int]:
    result = dict(a)
    for key, value in b.items():
        result[key] = result.get(key, 0) + value
    return result


@dataclass(frozen=True, slots=True)
class PhaseMetrics:
    """Counters for one phase.

    * ``accepted`` / ``rejected``: records that passed / failed validation.
    * ``present`` / ``applicable``: per field, how many accepted records had a value, out of
      how many records where the field applies (fill rate = present / applicable).
    * ``outcomes``: fetch outcomes (OK, BLOCKED, ...) of the requests made in this phase.
    """

    accepted: int = 0
    rejected: int = 0
    present: Mapping[str, int] = field(default_factory=dict[str, int])
    applicable: Mapping[str, int] = field(default_factory=dict[str, int])
    outcomes: Mapping[FetchOutcome, int] = field(default_factory=dict[FetchOutcome, int])

    @property
    def seen(self) -> int:
        return self.accepted + self.rejected

    @property
    def rejected_ratio(self) -> float:
        return self.rejected / self.seen if self.seen else 0.0

    def fill_rate(self, name: str) -> float | None:
        total = self.applicable.get(name, 0)
        return self.present.get(name, 0) / total if total else None

    def fill_rates(self) -> dict[str, float]:
        return {name: self.present.get(name, 0) / n for name, n in self.applicable.items() if n}

    def outcome_count(self, outcome: FetchOutcome) -> int:
        return self.outcomes.get(outcome, 0)

    # -------------------------------------------------------------- builders
    def with_outcome(self, outcome: FetchOutcome, count: int = 1) -> PhaseMetrics:
        return self + PhaseMetrics(outcomes={outcome: count})

    def with_accepted(self, presence: Mapping[str, bool]) -> PhaseMetrics:
        return self + PhaseMetrics(
            accepted=1,
            present={name: 1 for name, has in presence.items() if has},
            applicable=dict.fromkeys(presence, 1),
        )

    def with_rejected(self, count: int = 1) -> PhaseMetrics:
        return self + PhaseMetrics(rejected=count)

    def __add__(self, other: PhaseMetrics) -> PhaseMetrics:
        return PhaseMetrics(
            accepted=self.accepted + other.accepted,
            rejected=self.rejected + other.rejected,
            present=_add_counts(self.present, other.present),
            applicable=_add_counts(self.applicable, other.applicable),
            outcomes=_add_counts(self.outcomes, other.outcomes),
        )


@dataclass(frozen=True, slots=True)
class DiscoveryCoverage:
    """How much of the search result set discovery could reach.

    Sites cap pagination (OLX: ~1000 results per search). ``truncated`` means the site
    reported more results than can be paginated, so the search should be split.
    """

    pages: int = 0
    total_reported: int | None = None
    """Largest total the site reported (may itself be capped by the site)."""
    truncated: bool = False

    def __add__(self, other: DiscoveryCoverage) -> DiscoveryCoverage:
        totals = [t for t in (self.total_reported, other.total_reported) if t is not None]
        return DiscoveryCoverage(
            pages=self.pages + other.pages,
            total_reported=max(totals) if totals else None,
            truncated=self.truncated or other.truncated,
        )


@dataclass(frozen=True, slots=True)
class RunMetrics:
    discovery: PhaseMetrics = field(default_factory=PhaseMetrics)
    enrichment: PhaseMetrics = field(default_factory=PhaseMetrics)
    extraction: PhaseMetrics = field(default_factory=PhaseMetrics)
    usage: TokenUsage = field(default_factory=TokenUsage)
    coverage: DiscoveryCoverage = field(default_factory=DiscoveryCoverage)
    failed_jobs: int = 0
    """Work items that ran out of retries (or failed permanently)."""

    def phase(self, phase: Phase) -> PhaseMetrics:
        match phase:
            case Phase.DISCOVERY:
                return self.discovery
            case Phase.ENRICHMENT:
                return self.enrichment
            case Phase.EXTRACTION:
                return self.extraction

    @classmethod
    def for_phase(cls, phase: Phase, metrics: PhaseMetrics) -> RunMetrics:
        match phase:
            case Phase.DISCOVERY:
                return cls(discovery=metrics)
            case Phase.ENRICHMENT:
                return cls(enrichment=metrics)
            case Phase.EXTRACTION:
                return cls(extraction=metrics)

    def __add__(self, other: RunMetrics) -> RunMetrics:
        return RunMetrics(
            discovery=self.discovery + other.discovery,
            enrichment=self.enrichment + other.enrichment,
            extraction=self.extraction + other.extraction,
            usage=self.usage + other.usage,
            coverage=self.coverage + other.coverage,
            failed_jobs=self.failed_jobs + other.failed_jobs,
        )

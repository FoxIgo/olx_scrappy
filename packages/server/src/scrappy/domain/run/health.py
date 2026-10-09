"""Run health: degraded detection (ADR 0005) and the final status of a run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scrappy.domain.run.metrics import Phase, RunMetrics
from scrappy.domain.run.status import RunStatus
from scrappy.domain.shared import FetchOutcome, InvalidValueError


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    """Per-source thresholds (config). Crossing any of them makes the run DEGRADED."""

    max_rejected_ratio: float = 0.05
    """Per phase, share of records rejected by validation."""
    min_fill_rates: Mapping[Phase, Mapping[str, float]] = field(
        default_factory=dict[Phase, Mapping[str, float]]
    )
    """E.g. ``{DISCOVERY: {"price": 0.95}}``."""
    min_sample: int = 5
    """Phases with fewer records than this are not judged (avoids noise on tiny runs)."""

    def __post_init__(self) -> None:
        ratios = [self.max_rejected_ratio] + [
            r for rates in self.min_fill_rates.values() for r in rates.values()
        ]
        if any(not 0.0 <= r <= 1.0 for r in ratios):
            raise InvalidValueError("ratios must be within [0, 1]")
        if self.min_sample < 0:
            raise InvalidValueError("min_sample must be >= 0")


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: RunStatus
    """``COMPLETED`` or ``DEGRADED``."""
    reasons: tuple[str, ...] = ()


def run_health(metrics: RunMetrics, thresholds: HealthThresholds) -> HealthReport:
    """Check rejection ratios and fill rates; report which ones dropped (ADR 0005 section 3)."""
    reasons: list[str] = []
    for phase in Phase:
        phase_metrics = metrics.phase(phase)
        if phase_metrics.seen < thresholds.min_sample:
            continue
        if phase_metrics.rejected_ratio > thresholds.max_rejected_ratio:
            reasons.append(
                f"{phase.value}: rejected {phase_metrics.rejected}/{phase_metrics.seen} "
                f"records ({phase_metrics.rejected_ratio:.0%} > "
                f"{thresholds.max_rejected_ratio:.0%})"
            )
        for name, minimum in sorted(thresholds.min_fill_rates.get(phase, {}).items()):
            rate = phase_metrics.fill_rate(name)
            if rate is not None and rate < minimum:
                reasons.append(
                    f"{phase.value}: field '{name}' fill rate {rate:.0%} < {minimum:.0%}"
                )
    status = RunStatus.DEGRADED if reasons else RunStatus.COMPLETED
    return HealthReport(status, tuple(reasons))


@dataclass(frozen=True, slots=True)
class RunConclusion:
    status: RunStatus
    reasons: tuple[str, ...] = ()
    """Why the run is not COMPLETED."""
    warnings: tuple[str, ...] = ()
    """Things the user should know that do not change the status (e.g. truncation)."""


def conclude_run(metrics: RunMetrics, thresholds: HealthThresholds) -> RunConclusion:
    """Final status once a run has no unfinished work.

    Precedence: FAILED (no search page could be fetched) > DEGRADED (parser drift, the most
    actionable signal) > PARTIAL (some work items ran out of retries) > COMPLETED.
    """
    warnings: list[str] = []
    if metrics.coverage.truncated:
        total = metrics.coverage.total_reported
        warnings.append(
            "search results truncated by the site"
            + (f" ({total} reported)" if total is not None else "")
            + "; split the search (price ranges, region, category) to reach every offer"
        )
    if metrics.discovery.outcome_count(FetchOutcome.OK) == 0:
        return RunConclusion(
            RunStatus.FAILED, ("no search page could be fetched",), tuple(warnings)
        )
    health = run_health(metrics, thresholds)
    reasons = list(health.reasons)
    if metrics.failed_jobs:
        reasons.append(f"{metrics.failed_jobs} work item(s) failed after retries")
    if health.status is RunStatus.DEGRADED:
        status = RunStatus.DEGRADED
    elif metrics.failed_jobs:
        status = RunStatus.PARTIAL
    else:
        status = RunStatus.COMPLETED
    return RunConclusion(status, tuple(reasons), tuple(warnings))

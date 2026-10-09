"""ScrapeRun aggregate, run metrics and health rules (R6, ADR 0005)."""

from scrappy.domain.run.health import (
    HealthReport,
    HealthThresholds,
    RunConclusion,
    conclude_run,
    run_health,
)
from scrappy.domain.run.metrics import DiscoveryCoverage, Phase, PhaseMetrics, RunMetrics
from scrappy.domain.run.run import ScrapeRun
from scrappy.domain.run.status import RunStatus

__all__ = [
    "DiscoveryCoverage",
    "HealthReport",
    "HealthThresholds",
    "Phase",
    "PhaseMetrics",
    "RunConclusion",
    "RunMetrics",
    "RunStatus",
    "ScrapeRun",
    "conclude_run",
    "run_health",
]

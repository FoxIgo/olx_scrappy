"""ScrapeRun aggregate (R6, ADR 0005)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from scrappy.domain.run.health import RunConclusion
from scrappy.domain.run.metrics import RunMetrics
from scrappy.domain.run.status import RunStatus
from scrappy.domain.search import SavedSearch, SearchName
from scrappy.domain.shared import InvalidValueError, RunId, SourceId, require_aware


@dataclass(eq=False, slots=True)
class ScrapeRun:
    """One execution of a saved search. Its work items live in the job queue (ADR 0006)."""

    id: RunId
    search: SearchName
    source: SourceId
    started_at: datetime
    status: RunStatus = RunStatus.RUNNING
    finished_at: datetime | None = None
    metrics: RunMetrics = field(default_factory=RunMetrics)
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    """A sample of work-item errors (the "error log" of R6)."""

    def __post_init__(self) -> None:
        require_aware(self.started_at, "started_at")

    @classmethod
    def start(cls, run_id: RunId, search: SavedSearch, at: datetime) -> ScrapeRun:
        return cls(id=run_id, search=search.name, source=search.source, started_at=at)

    @property
    def is_running(self) -> bool:
        return self.status is RunStatus.RUNNING

    def finish(
        self,
        conclusion: RunConclusion,
        metrics: RunMetrics,
        at: datetime,
        errors: tuple[str, ...] = (),
    ) -> None:
        if conclusion.status is RunStatus.RUNNING:
            raise InvalidValueError("a run cannot finish as RUNNING")
        self.status = conclusion.status
        self.reasons = conclusion.reasons
        self.warnings = conclusion.warnings
        self.metrics = metrics
        self.errors = errors
        self.finished_at = require_aware(at, "at")

    def reopen(self) -> None:
        """Resume (R6): the run is running again until its re-queued work is done."""
        self.status = RunStatus.RUNNING
        self.finished_at = None

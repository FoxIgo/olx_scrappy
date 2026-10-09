from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    """Finished, but some work items failed after all retries."""
    DEGRADED = "degraded"
    """Finished, but data-quality thresholds were crossed (parser drift, ADR 0005)."""
    FAILED = "failed"
    """Nothing useful happened (not even one search page fetched)."""

    @property
    def is_finished(self) -> bool:
        return self is not RunStatus.RUNNING

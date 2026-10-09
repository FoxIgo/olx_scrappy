"""Exceptions a job handler raises when it cannot complete a job."""

from __future__ import annotations

from datetime import timedelta

from scrappy.application.jobs.model import JobResult


class JobError(Exception):
    def __init__(self, message: str, *, result: JobResult | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.result = result
        """Metrics of this attempt; stored if the job ends up FAILED."""


class RetryableJobError(JobError):
    """Try again later (BLOCKED, TRANSIENT, provider hiccup). Subject to the retry policy."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: timedelta | None = None,
        result: JobResult | None = None,
    ) -> None:
        super().__init__(message, result=result)
        self.retry_after = retry_after


class PermanentJobError(JobError):
    """Retrying cannot help (missing run/search/offer, unknown source). Fails immediately."""

"""Classification of a fetch attempt (ADR 0004 section 8).

Lives in the domain because offer status rules (R9) and run metrics (ADR 0005) depend on it.
"""

from __future__ import annotations

from enum import StrEnum


class FetchOutcome(StrEnum):
    OK = "ok"
    """Real content was received (it may still fail record validation)."""
    BLOCKED = "blocked"
    """403/429, captcha or challenge page. Retry later, possibly with another engine."""
    NOT_FOUND = "not_found"
    """404 / "offer does not exist". A valid answer, not an error."""
    GONE = "gone"
    """The page exists but the offer was removed or sold (R9). A valid answer."""
    TRANSIENT = "transient"
    """Network error, timeout, 5xx. Retry."""

    @property
    def is_retryable(self) -> bool:
        return self in (FetchOutcome.BLOCKED, FetchOutcome.TRANSIENT)

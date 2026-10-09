"""Persistent per-profile status: quota blocks and the daily request counter (ADR 0010).

Kept in the database (not in the extractor process) so that ``q health`` and
``scrappy extract status`` in another process can report it, and so that a daily limit
survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from scrappy.domain.shared import InvalidValueError, require_aware, require_aware_or_none


@dataclass(eq=False, slots=True)
class ProfileStatus:
    profile: str
    updated_at: datetime
    blocked_until: datetime | None = None
    """Quota exhausted (HTTP 402, credits): skip the profile until then."""
    reason: str | None = None
    usage_day: str | None = None
    """UTC date (``YYYY-MM-DD``) that :attr:`requests_today` counts."""
    requests_today: int = 0

    def __post_init__(self) -> None:
        require_aware(self.updated_at, "updated_at")
        require_aware_or_none(self.blocked_until, "blocked_until")
        if self.requests_today < 0:
            raise InvalidValueError("requests_today must be >= 0")

    @classmethod
    def new(cls, profile: str, now: datetime) -> ProfileStatus:
        return cls(profile=profile, updated_at=now)

    def is_blocked(self, now: datetime) -> bool:
        return self.blocked_until is not None and self.blocked_until > now

    def block(self, until: datetime, reason: str, now: datetime) -> None:
        self.blocked_until = until
        self.reason = reason[:500]
        self.updated_at = now

    def requests_on(self, now: datetime) -> int:
        return self.requests_today if self.usage_day == _day(now) else 0

    def remaining_today(self, daily_limit: int | None, now: datetime) -> int | None:
        if daily_limit is None:
            return None
        return max(0, daily_limit - self.requests_on(now))

    def count_requests(self, count: int, now: datetime) -> None:
        day = _day(now)
        if self.usage_day != day:
            self.usage_day = day
            self.requests_today = 0
        self.requests_today += count
        self.updated_at = now


def _day(at: datetime) -> str:
    return require_aware(at, "at").astimezone(UTC).date().isoformat()

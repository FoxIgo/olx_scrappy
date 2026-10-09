"""Time helpers. The domain never reads the clock; callers pass datetimes in."""

from __future__ import annotations

from datetime import datetime

from scrappy.domain.shared.errors import InvalidValueError


def require_aware(value: datetime, name: str) -> datetime:
    """Return ``value`` if it is timezone-aware, else raise."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidValueError(f"{name} must be a timezone-aware datetime")
    return value


def require_aware_or_none(value: datetime | None, name: str) -> datetime | None:
    return None if value is None else require_aware(value, name)

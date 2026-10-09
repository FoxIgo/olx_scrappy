"""System adapters: clock and id generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


class SystemClock:
    """``Clock`` port: timezone-aware UTC now."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    """``IdGenerator`` port: ``uuid4().hex`` (no ``:``)."""

    def new_id(self) -> str:
        return uuid.uuid4().hex

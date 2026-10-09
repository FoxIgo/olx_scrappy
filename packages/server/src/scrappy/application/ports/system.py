"""Small system ports: clock, id generation and the category catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from scrappy.domain.category import CategoryCatalog


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware (UTC)."""
        ...


class IdGenerator(Protocol):
    def new_id(self) -> str:
        """A new unique, opaque id without ':' (e.g. ``uuid4().hex``)."""
        ...


class CategoryProvider(Protocol):
    """Read-only source of category definitions (``categories.yaml`` now, a table later).

    Not part of the unit of work: categories are configuration, not transactional state.
    """

    async def catalog(self) -> CategoryCatalog: ...

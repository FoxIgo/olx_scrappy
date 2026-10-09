"""Fake clock, id generator and category provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scrappy.domain.category import CategoryCatalog


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta = timedelta(seconds=1)) -> datetime:
        self.current += delta
        return self.current


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"{self._prefix}{self._next:05d}"


class StaticCategoryProvider:
    def __init__(self, catalog: CategoryCatalog) -> None:
        self.current = catalog

    async def catalog(self) -> CategoryCatalog:
        return self.current

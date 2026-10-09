"""Component repository port (CPU/GPU components, aliases, benchmark scores). Reached
through ``UnitOfWork``; the general repository contract is in ``repositories.py``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from scrappy.domain.component import Benchmark, Component, ComponentAlias, ComponentKind


@dataclass(frozen=True, slots=True)
class ComponentWithBenchmarks:
    component: Component
    benchmarks: tuple[Benchmark, ...]

    @property
    def sort_key(self) -> tuple[float, str]:
        """Best score first, components without a score last, then by name."""
        return (-max((b.score for b in self.benchmarks), default=-1.0), self.component.name)


class ComponentRepository(Protocol):
    async def add_missing(self, components: Sequence[Component]) -> int:
        """Insert components whose id is new; existing rows are left untouched (curated
        names and traits survive a re-import). Returns how many were inserted."""
        ...

    async def add_aliases(self, aliases: Sequence[ComponentAlias]) -> int:
        """Insert aliases that do not exist yet; returns how many were inserted."""
        ...

    async def save_benchmarks(self, benchmarks: Sequence[Benchmark]) -> None:
        """Upsert by ``(component_id, source, metric)``."""
        ...

    async def get(self, component_id: str) -> Component | None: ...

    async def find(
        self, *, kind: ComponentKind | None = None, search: str | None = None
    ) -> list[ComponentWithBenchmarks]:
        """Components with all their benchmarks. ``search`` is a case-insensitive substring
        of the name or of the slug of the search text. Ordered by the best score, then name."""
        ...

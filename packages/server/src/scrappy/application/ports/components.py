"""Component repository port (CPU/GPU components, aliases, benchmark scores). Reached
through ``UnitOfWork``; the general repository contract is in ``repositories.py``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from scrappy.domain.component import (
    Benchmark,
    Component,
    ComponentAlias,
    ComponentKind,
    OfferComponentLink,
    ResolutionMethod,
)
from scrappy.domain.offer import OfferId


@dataclass(frozen=True, slots=True)
class ComponentWithBenchmarks:
    component: Component
    benchmarks: tuple[Benchmark, ...]

    @property
    def sort_key(self) -> tuple[float, str]:
        """Best score first, components without a score last, then by name."""
        return (-max((b.score for b in self.benchmarks), default=-1.0), self.component.name)


@dataclass(frozen=True, slots=True)
class ResolutionTask:
    """One raw CPU/GPU text of an offer's current extraction that needs (re-)resolving."""

    offer_id: OfferId
    category: str
    kind: ComponentKind
    raw_text: str
    vram_gb: int | None


@dataclass(frozen=True, slots=True)
class UnresolvedText:
    """A raw text nothing matched, lower-cased, with how many offers carry it."""

    kind: ComponentKind
    raw_text: str
    offers: int


class ComponentLlmFallback(Protocol):
    """Extension point for ``ResolutionMethod.LLM`` (not implemented yet, ADR 0011 section 3).

    Called only for texts the matcher left unresolved. It must choose from the short
    ``candidates`` list (never invent ids) and return the chosen component id, or ``None``.
    """

    async def pick(
        self, kind: ComponentKind, raw_text: str, candidates: Sequence[Component]
    ) -> str | None: ...


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

    async def list_components(self) -> list[Component]:
        """Every component (no benchmarks), for building the matcher."""
        ...

    async def list_aliases(self) -> list[ComponentAlias]: ...

    async def save_alias(self, alias: ComponentAlias) -> None:
        """Upsert by ``(kind, alias)``: a manual alias may repoint an existing one."""
        ...

    # ---- offer -> component links (the resolution backlog is a query, like extraction's)

    async def resolution_backlog(
        self, resolver_version: int, *, limit: int | None = None
    ) -> list[ResolutionTask]:
        """Raw ``cpu``/``gpu`` texts of the *current* extractions (any category) that have no
        link, a link made from a different raw text, or one from an older resolver version.
        Blank texts are skipped. Newest offers first."""
        ...

    async def count_resolution_backlog(self, resolver_version: int) -> int: ...

    async def save_links(self, links: Sequence[OfferComponentLink]) -> None:
        """Upsert by ``(offer, kind)``."""
        ...

    async def linked_raw_texts(self, kind: ComponentKind) -> list[str]:
        """Distinct raw texts that have a link."""
        ...

    async def mark_links_stale(self, kind: ComponentKind, raw_texts: Sequence[str]) -> int:
        """Make the links of these raw texts older than any resolver version, so the next
        resolve run redoes them. Returns the number of links."""
        ...

    async def link_counts(self) -> dict[tuple[ComponentKind, ResolutionMethod], int]: ...

    async def top_unresolved(self, limit: int) -> list[UnresolvedText]:
        """Most frequent unresolved raw texts (case-insensitive), most offers first."""
        ...

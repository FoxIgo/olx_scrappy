"""Ports of the scoring read side (ADR 0011 section 5): strategies and component facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from scrappy.domain.component import ComponentKind, ResolutionMethod
from scrappy.domain.offer import OfferId
from scrappy.domain.scoring import Strategy


@dataclass(frozen=True, slots=True)
class ComponentFact:
    """One benchmark score reached through an offer's CPU/GPU link (facts, as measured)."""

    offer_id: OfferId
    kind: ComponentKind
    component_id: str
    component_name: str
    source: str
    metric: str
    score: float
    samples: int
    confidence: float
    method: ResolutionMethod


class ScoringProvider(Protocol):
    """Source of strategies (``config/scoring.yaml``). Configuration, not transactional state;
    re-read on every call so edits apply without a restart. Raises on an invalid file."""

    async def strategies(self) -> Mapping[str, Strategy]: ...


class ScoringQueries(Protocol):
    """Read side for ranking. Committed data only, not part of the unit of work."""

    async def component_facts(self, offer_ids: Sequence[OfferId]) -> list[ComponentFact]:
        """Benchmark scores of the components linked to ``offer_ids`` (one row per offer, kind,
        source, metric), fetched in chunks, never one query per offer. Unresolved links and
        components without a benchmark yield no row."""
        ...

    async def component_offer_counts(self) -> dict[str, int]:
        """``component_id -> number of offers linked to it`` (components with none are absent)."""
        ...

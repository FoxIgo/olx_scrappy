"""Fakes of the scoring ports: fixed strategies and canned component facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scrappy.application.ports.scoring import ComponentFact
from scrappy.domain.offer import OfferId
from scrappy.domain.scoring import Strategy


class StaticScoringProvider:
    def __init__(self, strategies: Mapping[str, Strategy]) -> None:
        self.current = dict(strategies)

    async def strategies(self) -> Mapping[str, Strategy]:
        return self.current


class InMemoryScoringQueries:
    def __init__(self) -> None:
        self.facts: list[ComponentFact] = []
        self.counts: dict[str, int] = {}
        self.fact_calls: list[list[OfferId]] = []

    async def component_facts(self, offer_ids: Sequence[OfferId]) -> list[ComponentFact]:
        self.fact_calls.append(list(offer_ids))
        wanted = set(offer_ids)
        return [f for f in self.facts if f.offer_id in wanted]

    async def component_offer_counts(self) -> dict[str, int]:
        return dict(self.counts)

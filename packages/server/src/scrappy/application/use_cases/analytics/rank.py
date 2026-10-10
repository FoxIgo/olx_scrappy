"""``q rank``, ``q strategies`` and ``q components``: deal ranking by price per performance
(ADR 0011 sections 5 and 6).

Facts are read as stored (attributes of the latest extraction, benchmark scores of the linked
CPU/GPU); the strategy, loaded from config, is the only interpretation, computed per query.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import OfferRow
from scrappy.application.ports.scoring import ComponentFact, ScoringProvider, ScoringQueries
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics.common import (
    Answer,
    Json,
    QueryScope,
    ScopeResolver,
    fixed_price,
)
from scrappy.domain.component import ComponentKind
from scrappy.domain.offer import OfferId
from scrappy.domain.scoring import FactValue, OfferScore, Strategy, Term, score_offer

DEFAULT_RANK_LIMIT = 20
DEFAULT_MIN_COVERAGE = 0.6
RANK_FIELDS = (
    "id",
    "title",
    "url",
    "price",
    "currency",
    "performance",
    "value",
    "coverage",
    "breakdown",
)
VALUE_PER = 1000


async def load_strategy(provider: ScoringProvider, name: str) -> Strategy:
    strategies = await provider.strategies()
    strategy = strategies.get(name)
    if strategy is None:
        known = ", ".join(strategies) or "none configured"
        raise InvalidRequestError(f"unknown strategy {name!r} (known: {known})")
    return strategy


def _filter_text(strategy: Strategy) -> list[str]:
    return [f"{p.attribute}{p.op.value}{p.value}" for p in strategy.filters]


def _term_view(term: Term) -> Json:
    view: Json = {
        "fact": term.name,
        "weight": term.weight,
        "baseline": term.baseline,
        "transform": term.transform.value,
    }
    if term.name != term.fact:
        view["resolves_to"] = term.fact
    if term.cap is not None:
        view["cap"] = term.cap
    if term.value_map is not None:
        view["map"] = dict(term.value_map)
    return view


class Strategies:
    """``q strategies``: the configured interpretations, with their terms."""

    def __init__(self, provider: ScoringProvider) -> None:
        self._provider = provider

    async def __call__(self) -> Answer:
        strategies = await self._provider.strategies()
        data: list[Json] = [
            {
                "name": s.name,
                "description": s.description,
                "category": str(s.category),
                "filters": _filter_text(s),
                "total_weight": round(s.total_weight, 6),
                "terms": [_term_view(t) for t in s.terms],
            }
            for s in strategies.values()
        ]
        notes = [
            "performance = sum over present terms of weight * transform(min(fact, cap) / baseline);"
            " linear: x, log: log2(1 + x); missing facts add 0 and lower coverage",
            f"value = performance / price * {VALUE_PER} (fixed-price offers only)",
        ]
        if not data:
            notes.append("no strategies configured (config/scoring.yaml)")
        return Answer(data, len(data), notes=notes)


@dataclass(slots=True)
class _Ranked:
    row: OfferRow
    price: Decimal
    currency: str
    score: OfferScore
    value: float


def _breakdown(row: OfferRow, score: OfferScore, components: Mapping[str, ComponentFact]) -> Json:
    view: Json = {}
    for item in score.terms:
        term = item.term
        if item.points is None:
            view[term.name] = "missing"
            continue
        entry: Json = {"points": round(item.points, 4)}
        fact = components.get(term.fact)
        if fact is not None:
            entry["value"] = round(fact.score, 2)
            entry["part"] = fact.component_name
            if fact.confidence < 1:
                entry["link_confidence"] = round(fact.confidence, 2)
        else:
            entry["value"] = row.attributes.get(term.fact)
        view[term.name] = entry
    return view


class Rank:
    """Offers of a scope scored by a strategy: hard filters, performance, coverage, value."""

    def __init__(
        self, resolver: ScopeResolver, provider: ScoringProvider, queries: ScoringQueries
    ) -> None:
        self._resolver = resolver
        self._provider = provider
        self._queries = queries

    async def __call__(
        self,
        scope: QueryScope,
        strategy_name: str,
        *,
        min_coverage: float = DEFAULT_MIN_COVERAGE,
        limit: int = DEFAULT_RANK_LIMIT,
        fields: Sequence[str] = (),
    ) -> Answer:
        if not 0 <= min_coverage <= 1:
            raise InvalidRequestError("min-coverage must be between 0 and 1")
        if limit < 1:
            raise InvalidRequestError("limit must be >= 1")
        strategy = await load_strategy(self._provider, strategy_name)
        scoped_scope = replace(
            scope, category=strategy.category, where=(*scope.where, *strategy.filters)
        )
        scoped = await self._resolver.rows(scoped_scope)
        outside = await self._resolver.count_outside_category(scoped_scope)
        attribute_fields = [f for f in fields if f not in RANK_FIELDS]
        for name in attribute_fields:
            if scoped.category is None or scoped.category.attribute(name) is None:
                known = (
                    ", ".join(s.name for s in scoped.category.attributes) if scoped.category else ""
                )
                raise InvalidRequestError(
                    f"unknown field {name!r}; fields: {', '.join(RANK_FIELDS)}; attributes: {known}"
                )
        notes = list(scoped.notes)

        priced: list[tuple[OfferRow, Decimal, str]] = []
        not_fixed = 0
        for row in scoped.rows:
            fixed = fixed_price(row)
            if fixed is None:
                not_fixed += 1
            else:
                priced.append((row, fixed[0], fixed[1]))

        by_offer = self._group(
            await self._queries.component_facts([r.offer_id for r, _, _ in priced])
        )
        ranked: list[_Ranked] = []
        below = 0
        for row, amount, currency in priced:
            components = by_offer.get(row.offer_id, {})
            facts: dict[str, FactValue] = dict(row.attributes)
            facts.update({key: fact.score for key, fact in components.items()})
            score = score_offer(strategy, facts)
            if score.coverage + 1e-9 < min_coverage:
                below += 1
                continue
            value = score.performance / float(amount) * VALUE_PER
            ranked.append(_Ranked(row, amount, currency, score, value))
        ranked.sort(key=lambda r: (-r.value, -r.score.performance, str(r.row.offer_id)))

        excluded = {
            "by filters": scoped.dropped_by_filter,
            f"not extracted as {strategy.category} (other category or no extraction yet)": outside,
            "without a fixed price": not_fixed,
            f"below coverage {min_coverage:g}": below,
        }
        parts = [f"{n} {reason}" for reason, n in excluded.items() if n]
        if parts:
            notes.append(f"excluded: {', '.join(parts)}")
        notes.append(
            f"strategy {strategy.name}: filters {_filter_text(strategy) or 'none'}; value is "
            f"performance per {VALUE_PER} of the offer currency; missing facts add 0 points "
            "(see breakdown), part names that are too vague stay missing"
        )
        if len({r.currency for r in ranked}) > 1:
            notes.append("several currencies in the result; values are not comparable across them")
        if not ranked:
            notes.append("nothing to rank: relax --min-coverage / --where or extract more offers")
        truncated = len(ranked) > limit
        if truncated:
            notes.append(f"showing the best {limit} of {len(ranked)} ranked offers")
        data = [
            self._view(r, by_offer.get(r.row.offer_id, {}), fields, attribute_fields)
            for r in ranked[:limit]
        ]
        return Answer(data, len(data), truncated, notes)

    @staticmethod
    def _group(facts: Sequence[ComponentFact]) -> dict[OfferId, dict[str, ComponentFact]]:
        grouped: dict[OfferId, dict[str, ComponentFact]] = {}
        for fact in facts:
            key = f"{fact.kind.value}.{fact.source}.{fact.metric}"
            grouped.setdefault(fact.offer_id, {})[key] = fact
        return grouped

    @staticmethod
    def _view(
        ranked: _Ranked,
        components: Mapping[str, ComponentFact],
        fields: Sequence[str],
        attribute_fields: Sequence[str],
    ) -> Json:
        row = ranked.row
        values: Json = {
            "id": str(row.offer_id),
            "title": row.title,
            "url": row.url,
            "price": ranked.price,
            "currency": ranked.currency,
            "performance": round(ranked.score.performance, 4),
            "value": round(ranked.value, 3),
            "coverage": round(ranked.score.coverage, 3),
            "breakdown": _breakdown(row, ranked.score, components),
        }
        wanted = [f for f in fields if f in RANK_FIELDS] if fields else list(RANK_FIELDS)
        view: Json = {name: values[name] for name in wanted}
        for name in attribute_fields:
            view[name] = row.attributes.get(name)
        return view


class Components:
    """``q components``: parts with their benchmark scores and how many offers link to them."""

    def __init__(self, *, uow: UnitOfWorkFactory, queries: ScoringQueries) -> None:
        self._uow = uow
        self._queries = queries

    async def __call__(
        self,
        *,
        kind: ComponentKind | None = None,
        search: str | None = None,
        limit: int = 50,
        linked_only: bool = False,
    ) -> Answer:
        if limit < 1:
            raise InvalidRequestError("limit must be >= 1")
        async with self._uow() as uow:
            found = await uow.components.find(kind=kind, search=search)
        counts = await self._queries.component_offer_counts()
        items = [(item, counts.get(item.component.id, 0)) for item in found]
        if linked_only:
            items = [(item, n) for item, n in items if n > 0]
            items.sort(key=lambda pair: (-pair[1], pair[0].sort_key))
        shown = items[:limit]
        data: list[Json] = [
            {
                "id": item.component.id,
                "kind": item.component.kind.value,
                "name": item.component.name,
                "segment": item.component.segment.value,
                "benchmarks": [
                    {
                        "source": b.source,
                        "metric": b.metric,
                        "score": round(b.score, 2),
                        "samples": b.samples,
                    }
                    for b in item.benchmarks
                ],
                "offers": n,
            }
            for item, n in shown
        ]
        truncated = len(items) > limit
        notes = [f"showing {limit} of {len(items)} components"] if truncated else []
        if not found:
            notes.append("no components; run `scrappy benchmarks import` first")
        return Answer(data, len(data), truncated, notes)

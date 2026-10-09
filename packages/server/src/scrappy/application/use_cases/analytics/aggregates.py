"""``q facets``, ``q stats`` and ``q deals``: aggregates over the scoped offers."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from scrappy.application.errors import InvalidRequestError
from scrappy.application.ports.analytics import OfferRow
from scrappy.application.use_cases.analytics.common import (
    Answer,
    Json,
    QueryScope,
    ScopeResolver,
    fixed_price,
    offer_brief,
    specs_for,
)
from scrappy.domain.analytics import (
    DEFAULT_MAX_RATIO,
    DEFAULT_MIN_GROUP,
    DealCandidate,
    count_facet,
    describe_key,
    find_deals,
    group_key,
    summarize,
)
from scrappy.domain.category import AttributeValue
from scrappy.domain.offer import PriceKind
from scrappy.domain.shared import InvalidValueError

DEFAULT_GROUP_LIMIT = 100
DEFAULT_DEAL_LIMIT = 20


def _price_notes(rows: Sequence[OfferRow]) -> tuple[list[tuple[OfferRow, Decimal, str]], list[str]]:
    """Rows with a FIXED price, and the notes about the rest."""
    usable: list[tuple[OfferRow, Decimal, str]] = []
    other: dict[str, int] = {}
    for row in rows:
        fixed = fixed_price(row)
        if fixed is None:
            kind = row.price_kind.value if row.price_kind is not None else "none"
            other[kind] = other.get(kind, 0) + 1
        else:
            usable.append((row, fixed[0], fixed[1]))
    notes: list[str] = []
    if other:
        parts = ", ".join(f"{n} {kind}" for kind, n in sorted(other.items()))
        notes.append(
            f"{sum(other.values())} offer(s) without a fixed price ({parts}) "
            "are excluded from price figures"
        )
    return usable, notes


class Facets:
    def __init__(self, resolver: ScopeResolver) -> None:
        self._resolver = resolver

    async def __call__(
        self, scope: QueryScope, attributes: Sequence[str], *, buckets: int = 5
    ) -> Answer:
        if not attributes:
            raise InvalidRequestError("give at least one --attr")
        scoped = await self._resolver.rows(scope)
        specs = specs_for(scoped.catalog, scoped.category, attributes)
        extracted = [r for r in scoped.rows if r.category is not None]
        notes = list(scoped.notes)
        if len(extracted) < len(scoped.rows):
            notes.append(
                f"{len(scoped.rows) - len(extracted)} offer(s) have no extraction yet; "
                "they are excluded"
            )
        data: list[Json] = []
        for spec in specs:
            applicable: list[AttributeValue | None] = []
            inapplicable = 0
            for row in extracted:
                category = scoped.catalog.get(row.category) if row.category else None
                if category is None or category.attribute(spec.name) is None:
                    inapplicable += 1
                else:
                    applicable.append(row.attributes.get(spec.name))
            facet = count_facet(applicable, buckets=buckets)
            if inapplicable:
                notes.append(
                    f"{inapplicable} extracted offer(s) are in a category without {spec.name!r}; "
                    "they are not counted"
                )
            item: Json = {
                "attribute": spec.name,
                "type": spec.type.value,
                "total": facet.total,
                "null": facet.null_count,
                "values": [{"value": v, "count": n} for v, n in facet.values],
            }
            if facet.numeric is not None:
                item["numeric"] = {
                    "min": facet.numeric.minimum,
                    "max": facet.numeric.maximum,
                    "buckets": [
                        {"from": b.low, "to": b.high, "count": b.count}
                        for b in facet.numeric.buckets
                    ],
                }
            data.append(item)
        return Answer(data, len(data), notes=notes)


class Stats:
    def __init__(self, resolver: ScopeResolver) -> None:
        self._resolver = resolver

    async def __call__(
        self,
        scope: QueryScope,
        by: Sequence[str] = (),
        *,
        metric: str = "price",
        limit: int = DEFAULT_GROUP_LIMIT,
    ) -> Answer:
        if metric != "price":
            raise InvalidRequestError("only --metric price is supported")
        scoped = await self._resolver.rows(scope)
        specs_for(scoped.catalog, scoped.category, by)  # validates names
        rows = scoped.rows
        notes = list(scoped.notes)
        if by:
            extracted = [r for r in rows if r.category is not None]
            if len(extracted) < len(rows):
                notes.append(
                    f"{len(rows) - len(extracted)} offer(s) have no extraction yet; "
                    "they are excluded"
                )
            rows = extracted
        usable, price_notes = _price_notes(rows)
        notes += price_notes

        groups: dict[tuple[object, str], tuple[Json, list[Decimal]]] = {}
        missing = 0
        for row, amount, currency in usable:
            key = group_key(row.attributes, by)
            if key is None:
                missing += 1
                continue
            shown: Json = {name: row.attributes[name] for name in by}
            groups.setdefault((key, currency), (shown, []))[1].append(amount)
        if missing:
            notes.append(f"{missing} offer(s) lack a value for {', '.join(by)} and are excluded")
        currencies = sorted({currency for _, currency in groups})
        if len(currencies) > 1:
            notes.append(
                f"prices in several currencies ({', '.join(currencies)}); groups are split per "
                "currency and never mixed"
            )
        data: list[Json] = []
        for (_, currency), (shown, amounts) in groups.items():
            summary = summarize(amounts)
            if summary is None:  # pragma: no cover - groups are never empty
                continue
            data.append(
                {
                    "group": shown,
                    "currency": currency,
                    "n": summary.n,
                    "min": summary.minimum,
                    "p25": summary.p25,
                    "median": summary.median,
                    "p75": summary.p75,
                    "max": summary.maximum,
                    "mean": summary.mean,
                }
            )
        data.sort(key=lambda g: (-int(str(g["n"])), str(g["group"]), str(g["currency"])))
        small = [g for g in data if int(str(g["n"])) < 5]
        if small:
            notes.append(f"{len(small)} group(s) have fewer than 5 offers; treat them as anecdotes")
        truncated = len(data) > limit
        if truncated:
            notes.append(f"showing {limit} of {len(data)} groups")
        return Answer(data[:limit], min(len(data), limit), truncated, notes)


class Deals:
    def __init__(self, resolver: ScopeResolver) -> None:
        self._resolver = resolver

    async def __call__(
        self,
        scope: QueryScope,
        compare_by: Sequence[str] = (),
        *,
        min_group: int = DEFAULT_MIN_GROUP,
        max_ratio: Decimal = DEFAULT_MAX_RATIO,
        limit: int = DEFAULT_DEAL_LIMIT,
    ) -> Answer:
        scoped = await self._resolver.rows(scope)
        specs_for(scoped.catalog, scoped.category, compare_by)
        notes = list(scoped.notes)
        extracted = [r for r in scoped.rows if r.category is not None]
        if len(extracted) < len(scoped.rows):
            notes.append(
                f"{len(scoped.rows) - len(extracted)} offer(s) have no extraction yet; "
                "they are excluded"
            )
        usable, price_notes = _price_notes(extracted)
        notes += price_notes
        by_id = {str(row.offer_id): row for row, _, _ in usable}
        # offers are only comparable inside one category: it is part of the group key
        candidates = [
            DealCandidate(
                str(row.offer_id),
                amount,
                currency,
                {**row.attributes, "category": str(row.category)},
            )
            for row, amount, currency in usable
        ]
        try:
            report = find_deals(
                candidates,
                ["category", *compare_by],
                min_group=min_group,
                max_ratio=max_ratio,
            )
        except InvalidValueError as error:
            raise InvalidRequestError(str(error)) from error
        if report.excluded_missing:
            notes.append(
                f"{report.excluded_missing} offer(s) lack a value for "
                f"{', '.join(compare_by)} and cannot be compared; excluded"
            )
        if report.small_groups:
            notes.append(
                f"{report.small_groups} group(s) with {report.small_group_offers} offer(s) have "
                f"fewer than {min_group} members and were not judged"
            )
        if report.mixed_currency_keys:
            notes.append(
                "some groups contain several currencies; they are compared per currency "
                f"({'; '.join(describe_key(k) for k in report.mixed_currency_keys)})"
            )
        if not report.deals:
            notes.append(
                f"no deals: {report.compared} offer(s) were compared against group medians"
            )
        data: list[Json] = []
        for deal in report.deals[:limit]:
            row = by_id[deal.candidate.offer_id]
            data.append(
                {
                    "offer": offer_brief(row),
                    "group": {name: value for name, value in deal.group if name != "category"},
                    "category": str(row.category),
                    "group_size": deal.group_size,
                    "group_median": deal.group_median.quantize(Decimal("0.01")),
                    "ratio": deal.ratio.quantize(Decimal("0.001")),
                    "reason": deal.reason,
                }
            )
        truncated = len(report.deals) > limit
        if truncated:
            notes.append(f"showing the {limit} best of {len(report.deals)} deals")
        return Answer(data, len(data), truncated, notes)


__all__ = ["Deals", "Facets", "PriceKind", "Stats"]

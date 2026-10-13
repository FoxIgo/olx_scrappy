"""Shared plumbing of the ``q`` use cases: scope resolution, filtering, views, answers.

Filter semantics (ADR 0009): search / status / relevance / category are applied by the
:class:`~scrappy.application.ports.analytics.AnalyticsQueries` adapter; ``--where`` is applied
here, in Python, with the domain's :class:`AttributePredicate` (the specification shared with
``offers list``). Besides the category's attributes, ``price`` (FIXED amount), ``title`` and
``location`` are pseudo-fields; they win over a same-named attribute.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.ports.analytics import AnalyticsQueries, OfferRow, OfferScope
from scrappy.application.ports.system import CategoryProvider
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.list_offers import typed_predicates
from scrappy.domain.category import (
    AttributeSpec,
    AttributeValue,
    Category,
    CategoryCatalog,
    CategoryName,
)
from scrappy.domain.extraction import AttributePredicate, Comparison
from scrappy.domain.offer import OfferStatus, PriceKind
from scrappy.domain.search import SearchName

type Json = dict[str, object]

PSEUDO_FIELDS = ("price", "title", "location", "has_delivery")
DEFAULT_STATUSES = frozenset({OfferStatus.ACTIVE})


@dataclass(frozen=True, slots=True)
class QueryScope:
    """The common ``q`` options."""

    search: SearchName | None = None
    category: CategoryName | None = None
    relevant_only: bool = True
    statuses: frozenset[OfferStatus] = DEFAULT_STATUSES
    where: tuple[AttributePredicate, ...] = ()
    """Raw predicates (string values), as parsed from ``--where``."""


@dataclass(slots=True)
class Answer:
    """What every ``q`` use case returns; presentation wraps it in the JSON envelope."""

    data: object
    count: int | None = None
    truncated: bool = False
    notes: list[str] = field(default_factory=list[str])


@dataclass(slots=True)
class ScopedRows:
    rows: list[OfferRow]
    catalog: CategoryCatalog
    category: Category | None
    """The schema ``--where`` was typed against (``--category``, else the search's)."""
    category_name: CategoryName | None
    notes: list[str]
    dropped_by_filter: int = 0
    """Offers removed by ``--where`` (price / title / attribute predicates)."""


def relevance_of(row: OfferRow, search: SearchName | None) -> bool | None:
    """Effective relevance for ``search``; without one: true if relevant in any search,
    false if known-irrelevant everywhere, else unknown."""
    values = [link.is_relevant for link in row.links if search is None or link.search == search]
    if True in values:
        return True
    if values and all(v is False for v in values):
        return False
    return None


def seen_at(row: OfferRow, search: SearchName | None) -> datetime:
    if search is not None:
        for link in row.links:
            if link.search == search:
                return link.last_seen_at
    return row.last_seen_at


def fixed_price(row: OfferRow) -> tuple[Decimal, str] | None:
    if row.price_kind is PriceKind.FIXED and row.price_amount is not None and row.price_currency:
        return row.price_amount, row.price_currency
    return None


class ScopeResolver:
    def __init__(
        self, *, uow: UnitOfWorkFactory, queries: AnalyticsQueries, categories: CategoryProvider
    ) -> None:
        self._uow = uow
        self._queries = queries
        self._categories = categories

    async def catalog(self) -> CategoryCatalog:
        return await self._categories.catalog()

    async def count_outside_category(self, scope: QueryScope) -> int:
        """Offers that match ``scope`` except for ``scope.category``: extracted as another
        category, or not extracted yet (they can never be seen through a category)."""
        if scope.category is None:
            return 0
        base = OfferScope(
            search=scope.search, relevant_only=scope.relevant_only, statuses=scope.statuses
        )
        everything = await self._queries.count_offers(base)
        inside = await self._queries.count_offers(replace(base, category=scope.category))
        return everything - inside

    async def rows(self, scope: QueryScope) -> ScopedRows:
        catalog = await self._categories.catalog()
        category_name = scope.category
        if scope.search is not None:
            async with self._uow() as uow:
                search = await uow.searches.get(scope.search)
            if search is None:
                raise NotFoundError(f"search {scope.search} not found")
            category_name = category_name or search.category
        if scope.category is not None and not catalog.is_known(scope.category):
            known = ", ".join(str(c.name) for c in catalog)
            raise InvalidRequestError(f"unknown category {scope.category} (known: {known})")
        category = catalog.get(category_name) if category_name is not None else None

        pseudo = [p for p in scope.where if p.attribute in PSEUDO_FIELDS]
        attributes = tuple(p for p in scope.where if p.attribute not in PSEUDO_FIELDS)
        typed_pseudo = [_typed_pseudo(p) for p in pseudo]
        typed_attributes: tuple[AttributePredicate, ...] = ()
        if attributes:
            if category is None:
                raise InvalidRequestError(
                    "attribute filters need --category or --search (use `q schema` to see them)"
                )
            typed_attributes = typed_predicates(category, attributes)

        offer_scope = OfferScope(
            search=scope.search,
            relevant_only=scope.relevant_only,
            statuses=scope.statuses,
            category=scope.category,
        )
        rows = await self._queries.offer_rows(offer_scope)
        notes: list[str] = []
        if scope.relevant_only:
            everything = await self._queries.count_offers(replace(offer_scope, relevant_only=False))
            if everything > len(rows):
                notes.append(
                    f"{everything - len(rows)} offer(s) matching the other filters are hidden "
                    "because they are not (yet known to be) relevant; use --all to include them"
                )
            if scope.search is None:
                notes.append("without --search, relevant means relevant in at least one search")

        dropped_by_filter = 0
        if typed_pseudo:
            kept = [r for r in rows if _matches(typed_pseudo, _pseudo_values(r))]
            dropped_by_filter += len(rows) - len(kept)
            rows = kept
        if typed_attributes:
            extracted = [r for r in rows if r.category is not None]
            if len(extracted) < len(rows):
                notes.append(
                    f"{len(rows) - len(extracted)} offer(s) have no extraction yet; "
                    "they are excluded by the attribute filters"
                )
            kept = [r for r in extracted if _matches(typed_attributes, r.attributes)]
            dropped_by_filter += len(extracted) - len(kept)
            rows = kept
        rows.sort(key=lambda r: (-seen_at(r, scope.search).timestamp(), str(r.offer_id)))
        return ScopedRows(rows, catalog, category, category_name, notes, dropped_by_filter)


def _matches(
    predicates: Sequence[AttributePredicate], values: Mapping[str, AttributeValue | None]
) -> bool:
    return all(p.matches(values) for p in predicates)


def _pseudo_values(row: OfferRow) -> dict[str, AttributeValue | None]:
    fixed = fixed_price(row)
    return {
        "price": None if fixed is None else fixed[0],
        "title": row.title,
        "location": row.location,
        "has_delivery": row.has_delivery,
    }


def _typed_pseudo(predicate: AttributePredicate) -> AttributePredicate:
    raw = str(predicate.value)
    if predicate.attribute == "has_delivery":
        if predicate.op not in (Comparison.EQ, Comparison.NE):
            raise InvalidRequestError("has_delivery filter only supports = and !=")
        val_str = raw.strip().lower()
        if val_str not in ("true", "false", "1", "0", "yes", "no"):
            raise InvalidRequestError("has_delivery filter must be true/false or yes/no")
        bval = val_str in ("true", "1", "yes")
        return AttributePredicate("has_delivery", predicate.op, bval)
    if predicate.attribute == "price":
        if predicate.op in (Comparison.CONTAINS, Comparison.NOT_CONTAINS):
            raise InvalidRequestError("~ needs a text field (price is numeric)")
        try:
            return AttributePredicate("price", predicate.op, Decimal(raw))
        except InvalidOperation:
            raise InvalidRequestError(f"price filter needs a number, got {raw!r}") from None
    if predicate.op not in (
        Comparison.EQ,
        Comparison.NE,
        Comparison.CONTAINS,
        Comparison.NOT_CONTAINS,
    ):
        raise InvalidRequestError(
            f"{predicate.op.value} needs a numeric field ({predicate.attribute})"
        )
    return AttributePredicate(predicate.attribute, predicate.op, raw)


def specs_for(
    catalog: CategoryCatalog, category: Category | None, names: Sequence[str]
) -> list[AttributeSpec]:
    """Attribute specs for ``names`` from ``category``, else the first category defining each."""
    specs: list[AttributeSpec] = []
    for name in names:
        spec = category.attribute(name) if category is not None else None
        if spec is None and category is None:
            spec = next((s for c in catalog if (s := c.attribute(name)) is not None), None)
        if spec is None:
            known = sorted(
                {s.name for c in catalog for s in c.attributes}
                if category is None
                else {s.name for s in category.attributes}
            )
            raise InvalidRequestError(
                f"unknown attribute {name!r}" + (f" (known: {', '.join(known)})" if known else "")
            )
        specs.append(spec)
    return specs


async def require_catalog_category(provider: CategoryProvider, name: CategoryName) -> Category:
    category = (await provider.catalog()).get(name)
    if category is None:
        raise InvalidRequestError(f"unknown category {name}")
    return category


# ------------------------------------------------------------------------------- views


def offer_price_view(row: OfferRow) -> Json:
    return {
        "kind": None if row.price_kind is None else row.price_kind.value,
        "amount": row.price_amount,
        "currency": row.price_currency,
        "negotiable": row.price_negotiable,
    }


def offer_brief(row: OfferRow) -> Json:
    return {
        "id": str(row.offer_id),
        "title": row.title,
        "price": row.price_amount,
        "currency": row.price_currency,
        "price_kind": None if row.price_kind is None else row.price_kind.value,
        "location": row.location,
        "url": row.url,
    }

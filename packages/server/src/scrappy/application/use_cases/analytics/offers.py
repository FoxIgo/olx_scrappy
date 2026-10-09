"""``q offers``, ``q offer`` and ``q export``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from scrappy.application.errors import InvalidRequestError, NotFoundError
from scrappy.application.extraction.prepare import prepare_description
from scrappy.application.ports.analytics import OfferRow
from scrappy.application.ports.unit_of_work import UnitOfWorkFactory
from scrappy.application.use_cases.analytics.common import (
    Answer,
    Json,
    QueryScope,
    ScopeResolver,
    offer_price_view,
    relevance_of,
    seen_at,
)
from scrappy.domain.category import OTHER_CATEGORY, AttributeValue, CategoryCatalog
from scrappy.domain.offer import FieldChange, OfferId, OfferSnapshot, Params, Price, TrackedField
from scrappy.domain.search import SearchName

BASE_FIELDS = (
    "id",
    "title",
    "price",
    "currency",
    "price_kind",
    "location",
    "status",
    "url",
    "first_seen_at",
    "last_seen_at",
    "category",
    "relevant",
)
SORTS = ("seen", "price", "price-desc")
DEFAULT_LIMIT = 50


def change_value(field_: TrackedField, value: object) -> object:
    """JSON-friendly form of one side of a :class:`FieldChange`."""
    if field_ is TrackedField.PRICE and isinstance(value, Price):
        return {
            "kind": value.kind.value,
            "amount": None if value.amount is None else value.amount.amount,
            "currency": None if value.amount is None else value.amount.currency,
            "negotiable": value.negotiable,
        }
    if field_ is TrackedField.PARAMS and value is not None:
        return dict(value.items) if isinstance(value, Params) else None
    if hasattr(value, "value") and not isinstance(value, str):
        return getattr(value, "value", None)
    return value


def change_view(change: FieldChange) -> Json:
    return {
        "field": change.field.value,
        "old": change_value(change.field, change.old),
        "new": change_value(change.field, change.new),
    }


def snapshot_view(snapshot: OfferSnapshot) -> Json:
    return {
        "at": snapshot.observed_at,
        "run_id": None if snapshot.run_id is None else str(snapshot.run_id),
        "changes": [change_view(c) for c in snapshot.changes],
    }


def all_attribute_names(catalog: CategoryCatalog) -> list[str]:
    names: list[str] = []
    for category in catalog:
        for spec in category.attributes:
            if spec.name not in names:
                names.append(spec.name)
    return names


class QueryOffers:
    def __init__(self, resolver: ScopeResolver) -> None:
        self._resolver = resolver

    async def __call__(
        self,
        scope: QueryScope,
        *,
        limit: int = DEFAULT_LIMIT,
        fields: Sequence[str] = (),
        sort: str = "seen",
    ) -> Answer:
        if sort not in SORTS:
            raise InvalidRequestError(f"unknown sort {sort!r}; expected one of: {', '.join(SORTS)}")
        if limit < 1:
            raise InvalidRequestError("limit must be >= 1")
        scoped = await self._resolver.rows(scope)
        attribute_names = all_attribute_names(scoped.catalog)
        base = list(fields) if fields else list(BASE_FIELDS)
        wanted_attributes = [f for f in base if f not in BASE_FIELDS]
        for name in wanted_attributes:
            if name not in attribute_names:
                raise InvalidRequestError(
                    f"unknown field {name!r}; fields: {', '.join(BASE_FIELDS)}; "
                    f"attributes: {', '.join(attribute_names) or '-'}"
                )
        base = [f for f in base if f in BASE_FIELDS]
        if not fields:
            wanted_attributes = (
                [s.name for s in scoped.category.attributes]
                if scoped.category is not None
                else attribute_names
            )

        rows = scoped.rows
        if sort != "seen":
            priced = [r for r in rows if r.price_amount is not None]
            rest = [r for r in rows if r.price_amount is None]
            priced.sort(key=lambda r: r.price_amount or Decimal(0), reverse=sort == "price-desc")
            rows = priced + rest
        shown = rows[:limit]
        notes = list(scoped.notes)
        truncated = len(rows) > limit
        if truncated:
            notes.append(f"showing {limit} of {len(rows)} matching offers; raise --limit or filter")
        data = [_row(r, scope, base, wanted_attributes) for r in shown]
        return Answer(data, len(data), truncated, notes)


def _row(row: OfferRow, scope: QueryScope, base: Sequence[str], attributes: Sequence[str]) -> Json:
    values: dict[str, object] = {
        "id": str(row.offer_id),
        "title": row.title,
        "price": row.price_amount,
        "currency": row.price_currency,
        "price_kind": None if row.price_kind is None else row.price_kind.value,
        "location": row.location,
        "status": row.status.value,
        "url": row.url,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": seen_at(row, scope.search),
        "category": None if row.category is None else str(row.category),
        "relevant": relevance_of(row, scope.search),
    }
    result: Json = {name: values[name] for name in base}
    if attributes:
        result["attributes"] = {name: row.attributes.get(name) for name in attributes}
    return result


class OfferDetail:
    def __init__(self, *, uow: UnitOfWorkFactory, description_chars: int = 2000) -> None:
        self._uow = uow
        self._chars = description_chars

    async def __call__(self, ids: Sequence[str]) -> Answer:
        if not ids:
            raise InvalidRequestError("give at least one offer id (source:external_id)")
        details: list[Json] = []
        missing: list[str] = []
        for raw in ids:
            try:
                offer_id = OfferId.parse(raw)
            except Exception as error:
                raise InvalidRequestError(str(error)) from error
            async with self._uow() as uow:
                offer = await uow.offers.get(offer_id)
                if offer is None:
                    missing.append(raw)
                    continue
                extraction = await uow.extractions.latest(offer_id)
                snapshots = await uow.offers.list_snapshots(offer_id)
                links = await uow.search_offers.list_for_offer(offer_id)
            description = offer.description
            if description:
                description, _ = prepare_description(description, self._chars)
            price = offer.price
            detail: Json = {
                "id": str(offer.id),
                "url": offer.url,
                "title": offer.title,
                "price": None if price is None else change_value(TrackedField.PRICE, price),
                "location": offer.location,
                "status": offer.status.value,
                "first_seen_at": offer.first_seen_at,
                "last_seen_at": offer.last_seen_at,
                "posted_at": offer.posted_at,
                "details_fetched_at": offer.details_fetched_at,
                "description": description,
                "params": dict(offer.params.items) if offer.params else {},
                "seller": None
                if offer.seller is None
                else {"name": offer.seller.name, "is_business": offer.seller.is_business},
                "extraction": None
                if extraction is None
                else {
                    "category": str(extraction.category),
                    "attributes": dict(extraction.attributes),
                    "notes": extraction.notes,
                    "provenance": {
                        "model": extraction.provenance.model,
                        "prompt_version": extraction.provenance.prompt_version,
                        "schema_version": extraction.provenance.schema_version,
                        "extracted_at": extraction.provenance.extracted_at,
                    },
                },
                "snapshots": [snapshot_view(s) for s in snapshots],
                "searches": [
                    {
                        "search": str(link.search),
                        "first_seen_at": link.first_seen_at,
                        "last_seen_at": link.last_seen_at,
                        "derived_relevance": link.derived_relevance,
                        "relevance_override": link.relevance_override,
                        "relevant": link.is_relevant,
                    }
                    for link in links
                ],
            }
            details.append(detail)
        if not details:
            raise NotFoundError(f"offer(s) not found: {', '.join(missing)}")
        notes = [f"not found: {', '.join(missing)}"] if missing else []
        return Answer(details, len(details), notes=notes)


# ---------------------------------------------------------------------------- export

EXPORT_BASE_COLUMNS = (
    "offer_id",
    "source",
    "title",
    "url",
    "status",
    "location",
    "price_kind",
    "price_amount",
    "currency",
    "negotiable",
    "first_seen_at",
    "last_seen_at",
    "search",
    "relevant",
    "category",
)
ATTRIBUTE_PREFIX = "attr_"


@dataclass(slots=True)
class ExportTable:
    columns: list[str]
    rows: list[list[object]]
    notes: list[str] = field(default_factory=list[str])


class ExportOffers:
    """A flat table, one row per offer: offer columns + ``attr_<name>`` per attribute of the
    exported categories (taken from the live catalog, so columns do not depend on which values
    happen to be null). No row limit: exports are complete."""

    def __init__(self, resolver: ScopeResolver) -> None:
        self._resolver = resolver

    async def __call__(self, scope: QueryScope) -> ExportTable:
        scoped = await self._resolver.rows(scope)
        catalog = scoped.catalog
        if scope.category is not None:
            names = [scope.category]
        else:
            names = sorted(
                {r.category for r in scoped.rows if r.category not in (None, OTHER_CATEGORY)},
                key=str,
            )  # pyright: ignore[reportArgumentType]
            if scoped.category_name is not None and scoped.category_name not in names:
                names.append(scoped.category_name)
                names.sort(key=str)
        attributes: list[str] = []
        for name in names:
            category = catalog.get(name)
            for spec in category.attributes if category is not None else ():
                if spec.name not in attributes:
                    attributes.append(spec.name)
        notes = list(scoped.notes)
        if len(names) > 1:
            notes.append(
                "attribute columns are the union of categories "
                f"{', '.join(map(str, names))}; cells are empty where a category lacks one"
            )
        unextracted = sum(1 for r in scoped.rows if r.category is None)
        if unextracted:
            notes.append(f"{unextracted} exported offer(s) have no extraction; attr_* are empty")
        columns = [*EXPORT_BASE_COLUMNS, *(ATTRIBUTE_PREFIX + a for a in attributes)]
        rows = [self._row(r, scope.search, attributes) for r in scoped.rows]
        notes.append(f"{len(rows)} row(s) exported")
        return ExportTable(columns, rows, notes)

    @staticmethod
    def _row(row: OfferRow, search: SearchName | None, attributes: Sequence[str]) -> list[object]:
        links = [link for link in row.links if search is None or link.search == search]
        values: Mapping[str, AttributeValue | None] = row.attributes
        return [
            str(row.offer_id),
            row.offer_id.source.value,
            row.title,
            row.url,
            row.status.value,
            row.location,
            None if row.price_kind is None else row.price_kind.value,
            row.price_amount,
            row.price_currency,
            row.price_negotiable,
            row.first_seen_at,
            seen_at(row, search) if search is not None else row.last_seen_at,
            ";".join(sorted(str(link.search) for link in links)),
            relevance_of(row, search),
            None if row.category is None else str(row.category),
            *(values.get(a) for a in attributes),
        ]


__all__ = [
    "ATTRIBUTE_PREFIX",
    "BASE_FIELDS",
    "EXPORT_BASE_COLUMNS",
    "ExportOffers",
    "ExportTable",
    "OfferDetail",
    "QueryOffers",
    "offer_price_view",
]

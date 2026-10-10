"""Domain object <-> table row conversion.

``*_values`` build the column dict to write; ``*_from`` rebuild the object from a row mapping
and the column collection to read from (``table.c`` or a subquery's ``.c``), so the same
code serves plain selects and the joined listing query.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import ColumnCollection

from scrappy.application.extraction.batch import BatchItem, BatchStatus, ExtractionBatch
from scrappy.application.extraction.profile_status import ProfileStatus
from scrappy.application.jobs.codec import decode_metrics, encode_metrics
from scrappy.domain.category import AttributeValue, CategoryName
from scrappy.domain.extraction import (
    ExtractionProvenance,
    ExtractionState,
    ExtractionTarget,
    OfferExtraction,
    TokenUsage,
)
from scrappy.domain.offer import (
    ContentHash,
    FieldChange,
    Offer,
    OfferId,
    OfferSnapshot,
    OfferStatus,
    Params,
    Price,
    PriceKind,
    SellerRef,
    TrackedField,
)
from scrappy.domain.run import RunStatus, ScrapeRun
from scrappy.domain.search import SavedSearch, SearchName, SearchOffer
from scrappy.domain.shared import Money, RunId, SourceId

type Row = Mapping[Any, Any]
type Cols = ColumnCollection[str, Any]


def offer_id_of(row: Row, c: Cols) -> OfferId:
    return OfferId(SourceId(row[c.source]), row[c.external_id])


# ---------------------------------------------------------------------------- JSON values


def params_to_json(params: Params | None) -> list[list[str]] | None:
    return None if params is None else [[k, v] for k, v in params.items]


def params_from_json(data: Sequence[Sequence[str]] | None) -> Params | None:
    return None if data is None else Params(tuple((k, v) for k, v in data))


def _price_to_json(price: Price) -> dict[str, Any]:
    return {
        "kind": price.kind.value,
        "amount": None if price.amount is None else str(price.amount.amount),
        "currency": None if price.amount is None else price.amount.currency,
        "negotiable": price.negotiable,
    }


def _price_from_json(data: Mapping[str, Any]) -> Price:
    amount = None
    if data["amount"] is not None:
        amount = Money(Decimal(data["amount"]), data["currency"])
    return Price(PriceKind(data["kind"]), amount, bool(data["negotiable"]))


def attributes_to_json(attributes: Mapping[str, AttributeValue | None]) -> dict[str, Any]:
    """Decimals become ``{"$decimal": "15.6"}`` so they survive JSON exactly and stay
    distinguishable from ints, bools and strings."""
    return {name: _attribute_to_json(v) for name, v in attributes.items()}


def _attribute_to_json(value: AttributeValue | None) -> Any:
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, tuple):
        return list(value)
    return value


def attributes_from_json(data: Mapping[str, Any]) -> dict[str, AttributeValue | None]:
    result: dict[str, AttributeValue | None] = {}
    for name, value in data.items():
        if isinstance(value, dict):
            result[name] = Decimal(cast("dict[str, str]", value)["$decimal"])
        elif isinstance(value, list):
            result[name] = tuple(cast("list[str]", value))
        else:
            result[name] = cast("AttributeValue | None", value)
    return result


def _change_value_to_json(field: TrackedField, value: object) -> Any:
    match field:
        case TrackedField.PRICE:
            return _price_to_json(cast(Price, value))
        case TrackedField.PARAMS:
            return params_to_json(cast(Params, value))
        case TrackedField.STATUS:
            return cast(OfferStatus, value).value
        case _:
            return value


def _change_value_from_json(field: TrackedField, data: Any) -> Any:
    match field:
        case TrackedField.PRICE:
            return _price_from_json(data)
        case TrackedField.PARAMS:
            return params_from_json(data)
        case TrackedField.STATUS:
            return OfferStatus(data)
        case _:
            return data


# ---------------------------------------------------------------------------- offers


def offer_values(offer: Offer) -> dict[str, Any]:
    price = offer.price
    seller = offer.seller
    return {
        "source": offer.id.source.value,
        "external_id": offer.id.external_id,
        "url": offer.url,
        "first_seen_at": offer.first_seen_at,
        "last_seen_at": offer.last_seen_at,
        "title": offer.title,
        "price_kind": None if price is None else price.kind.value,
        "price_amount": None if price is None or price.amount is None else str(price.amount.amount),
        "price_currency": None if price is None or price.amount is None else price.amount.currency,
        "price_negotiable": None if price is None else price.negotiable,
        "location": offer.location,
        "thumbnail_url": offer.thumbnail_url,
        "posted_at": offer.posted_at,
        "refreshed_at": offer.refreshed_at,
        "description": offer.description,
        "params": params_to_json(offer.params),
        "status": offer.status.value,
        "seller_external_id": None if seller is None else seller.external_id,
        "seller_name": None if seller is None else seller.name,
        "seller_is_business": None if seller is None else seller.is_business,
        "image_urls": list(offer.image_urls),
        "content_hash": None if offer.content_hash is None else offer.content_hash.value,
        "details_fetched_at": offer.details_fetched_at,
    }


def offer_from(row: Row, c: Cols) -> Offer:
    price = None
    if row[c.price_kind] is not None:
        amount = None
        if row[c.price_amount] is not None:
            amount = Money(Decimal(row[c.price_amount]), row[c.price_currency])
        price = Price(PriceKind(row[c.price_kind]), amount, bool(row[c.price_negotiable]))
    seller = None
    if (
        row[c.seller_external_id] is not None
        or row[c.seller_name] is not None
        or row[c.seller_is_business] is not None
    ):
        seller = SellerRef(row[c.seller_external_id], row[c.seller_name], row[c.seller_is_business])
    content_hash = row[c.content_hash]
    return Offer(
        id=offer_id_of(row, c),
        url=row[c.url],
        first_seen_at=row[c.first_seen_at],
        last_seen_at=row[c.last_seen_at],
        title=row[c.title],
        price=price,
        location=row[c.location],
        thumbnail_url=row[c.thumbnail_url],
        posted_at=row[c.posted_at],
        refreshed_at=row[c.refreshed_at],
        description=row[c.description],
        params=params_from_json(row[c.params]),
        status=OfferStatus(row[c.status]),
        seller=seller,
        image_urls=tuple(row[c.image_urls]),
        content_hash=None if content_hash is None else ContentHash(content_hash),
        details_fetched_at=row[c.details_fetched_at],
    )


def snapshot_values(snapshot: OfferSnapshot) -> dict[str, Any]:
    return {
        "source": snapshot.offer_id.source.value,
        "external_id": snapshot.offer_id.external_id,
        "observed_at": snapshot.observed_at,
        "run_id": None if snapshot.run_id is None else snapshot.run_id.value,
        "changes": [
            {
                "field": change.field.value,
                "old": _change_value_to_json(change.field, change.old),
                "new": _change_value_to_json(change.field, change.new),
            }
            for change in snapshot.changes
        ],
    }


def snapshot_from(row: Row, c: Cols) -> OfferSnapshot:
    changes: list[FieldChange] = []
    for item in row[c.changes]:
        field = TrackedField(item["field"])
        changes.append(
            FieldChange(
                field,
                _change_value_from_json(field, item["old"]),
                _change_value_from_json(field, item["new"]),
            )
        )
    run_id = row[c.run_id]
    return OfferSnapshot(
        offer_id_of(row, c),
        row[c.observed_at],
        tuple(changes),
        None if run_id is None else RunId(run_id),
    )


# ---------------------------------------------------------------------------- searches


def search_values(search: SavedSearch) -> dict[str, Any]:
    return {
        "name": search.name.value,
        "source": search.source.value,
        "url": search.url,
        "category": search.category.value,
        "created_at": search.created_at,
        "last_run_at": search.last_run_at,
    }


def search_from(row: Row, c: Cols) -> SavedSearch:
    return SavedSearch(
        name=SearchName(row[c.name]),
        source=SourceId(row[c.source]),
        url=row[c.url],
        category=CategoryName(row[c.category]),
        created_at=row[c.created_at],
        last_run_at=row[c.last_run_at],
    )


def link_values(link: SearchOffer) -> dict[str, Any]:
    return {
        "search": link.search.value,
        "source": link.offer_id.source.value,
        "external_id": link.offer_id.external_id,
        "first_seen_at": link.first_seen_at,
        "last_seen_at": link.last_seen_at,
        "derived_relevance": link.derived_relevance,
        "relevance_override": link.relevance_override,
    }


def link_from(row: Row, c: Cols) -> SearchOffer:
    return SearchOffer(
        search=SearchName(row[c.search]),
        offer_id=offer_id_of(row, c),
        first_seen_at=row[c.first_seen_at],
        last_seen_at=row[c.last_seen_at],
        derived_relevance=row[c.derived_relevance],
        relevance_override=row[c.relevance_override],
    )


# ---------------------------------------------------------------------------- extractions


def extraction_values(extraction: OfferExtraction) -> dict[str, Any]:
    provenance = extraction.provenance
    cost = extraction.usage.cost_usd
    return {
        "source": extraction.offer_id.source.value,
        "external_id": extraction.offer_id.external_id,
        "category": extraction.category.value,
        "attributes": attributes_to_json(extraction.attributes),
        "model": provenance.model,
        "prompt_version": provenance.prompt_version,
        "schema_version": provenance.schema_version,
        "content_hash": provenance.content_hash.value,
        "extracted_at": provenance.extracted_at,
        "prompt_tokens": extraction.usage.prompt_tokens,
        "completion_tokens": extraction.usage.completion_tokens,
        "cost_usd": None if cost is None else str(cost),
        "notes": extraction.notes,
        "catalog_fingerprint": provenance.catalog_fingerprint,
        "profile": provenance.profile,
        "provider": provenance.provider,
        "batch_id": provenance.batch_id,
        "cost_estimated": provenance.cost_estimated,
    }


def extraction_from(row: Row, c: Cols) -> OfferExtraction:
    cost = row[c.cost_usd]
    return OfferExtraction(
        offer_id=offer_id_of(row, c),
        category=CategoryName(row[c.category]),
        attributes=attributes_from_json(row[c.attributes]),
        provenance=ExtractionProvenance(
            model=row[c.model],
            prompt_version=row[c.prompt_version],
            schema_version=row[c.schema_version],
            content_hash=ContentHash(row[c.content_hash]),
            extracted_at=row[c.extracted_at],
            catalog_fingerprint=row[c.catalog_fingerprint],
            profile=row[c.profile],
            provider=row[c.provider],
            batch_id=row[c.batch_id],
            cost_estimated=bool(row[c.cost_estimated]),
        ),
        usage=TokenUsage(
            row[c.prompt_tokens], row[c.completion_tokens], None if cost is None else Decimal(cost)
        ),
        notes=row[c.notes],
    )


# ---------------------------------------------------------------------------- runs


def run_values(run: ScrapeRun) -> dict[str, Any]:
    return {
        "id": run.id.value,
        "search": run.search.value,
        "source": run.source.value,
        "started_at": run.started_at,
        "status": run.status.value,
        "finished_at": run.finished_at,
        "metrics": encode_metrics(run.metrics),
        "reasons": list(run.reasons),
        "warnings": list(run.warnings),
        "errors": list(run.errors),
    }


def run_from(row: Row, c: Cols) -> ScrapeRun:
    return ScrapeRun(
        id=RunId(row[c.id]),
        search=SearchName(row[c.search]),
        source=SourceId(row[c.source]),
        started_at=row[c.started_at],
        status=RunStatus(row[c.status]),
        finished_at=row[c.finished_at],
        metrics=decode_metrics(row[c.metrics]),
        reasons=tuple(row[c.reasons]),
        warnings=tuple(row[c.warnings]),
        errors=tuple(row[c.errors]),
    )


# ---------------------------------------------------------------------------- extraction state


def state_values(state: ExtractionState) -> dict[str, Any]:
    target = state.target
    return {
        "source": state.offer_id.source.value,
        "external_id": state.offer_id.external_id,
        "lease_owner": state.lease_owner,
        "lease_until": state.lease_until,
        "attempts": state.attempts,
        "last_error": state.last_error,
        "next_attempt_at": state.next_attempt_at,
        "parked": state.parked,
        "target_content_hash": None if target is None else target.content_hash.value,
        "target_catalog_fingerprint": None if target is None else target.catalog_fingerprint,
        "target_prompt_version": None if target is None else target.prompt_version,
        "forced": state.forced,
        "requested_profile": state.requested_profile,
        "updated_at": state.updated_at,
    }


def state_from(row: Row, c: Cols) -> ExtractionState:
    content_hash = row[c.target_content_hash]
    target = (
        None
        if content_hash is None
        else ExtractionTarget(
            ContentHash(content_hash),
            row[c.target_catalog_fingerprint] or "",
            row[c.target_prompt_version] or "",
        )
    )
    return ExtractionState(
        offer_id=offer_id_of(row, c),
        updated_at=row[c.updated_at],
        lease_owner=row[c.lease_owner],
        lease_until=row[c.lease_until],
        attempts=row[c.attempts],
        last_error=row[c.last_error],
        next_attempt_at=row[c.next_attempt_at],
        parked=bool(row[c.parked]),
        target=target,
        forced=bool(row[c.forced]),
        requested_profile=row[c.requested_profile],
    )


# ---------------------------------------------------------------------------- batches


def batch_values(batch: ExtractionBatch) -> dict[str, Any]:
    cost = batch.usage.cost_usd
    return {
        "id": batch.id,
        "profile": batch.profile,
        "provider": batch.provider,
        "model": batch.model,
        "prompt_version": batch.prompt_version,
        "catalog_fingerprint": batch.catalog_fingerprint,
        "status": batch.status.value,
        "parent_id": batch.parent_id,
        "provider_batch_id": batch.provider_batch_id,
        "created_at": batch.created_at,
        "submitting_at": batch.submitting_at,
        "submitted_at": batch.submitted_at,
        "finished_at": batch.finished_at,
        "item_count": len(batch.items),
        "prompt_tokens": batch.usage.prompt_tokens,
        "completion_tokens": batch.usage.completion_tokens,
        "cost_usd": None if cost is None else str(cost),
        "succeeded": batch.succeeded,
        "failed": batch.failed,
        "stale": batch.stale,
        "error": batch.error,
    }


def batch_item_values(batch: ExtractionBatch) -> list[dict[str, Any]]:
    return [
        {
            "batch_id": batch.id,
            "position": position,
            "source": item.offer_id.source.value,
            "external_id": item.offer_id.external_id,
            "content_hash": item.content_hash.value,
        }
        for position, item in enumerate(batch.items)
    ]


def batch_from(row: Row, c: Cols, items: Sequence[Row], ic: Cols) -> ExtractionBatch:
    cost = row[c.cost_usd]
    return ExtractionBatch(
        id=row[c.id],
        profile=row[c.profile],
        provider=row[c.provider],
        model=row[c.model],
        prompt_version=row[c.prompt_version],
        catalog_fingerprint=row[c.catalog_fingerprint],
        items=tuple(
            BatchItem(offer_id_of(item, ic), ContentHash(item[ic.content_hash])) for item in items
        ),
        created_at=row[c.created_at],
        status=BatchStatus(row[c.status]),
        parent_id=row[c.parent_id],
        provider_batch_id=row[c.provider_batch_id],
        submitting_at=row[c.submitting_at],
        submitted_at=row[c.submitted_at],
        finished_at=row[c.finished_at],
        usage=TokenUsage(
            row[c.prompt_tokens], row[c.completion_tokens], None if cost is None else Decimal(cost)
        ),
        succeeded=row[c.succeeded],
        failed=row[c.failed],
        stale=row[c.stale],
        error=row[c.error],
    )


# ---------------------------------------------------------------------------- profile status


def profile_status_values(status: ProfileStatus) -> dict[str, Any]:
    return {
        "profile": status.profile,
        "blocked_until": status.blocked_until,
        "reason": status.reason,
        "usage_day": status.usage_day,
        "requests_today": status.requests_today,
        "updated_at": status.updated_at,
    }


def profile_status_from(row: Row, c: Cols) -> ProfileStatus:
    return ProfileStatus(
        profile=row[c.profile],
        updated_at=row[c.updated_at],
        blocked_until=row[c.blocked_until],
        reason=row[c.reason],
        usage_day=row[c.usage_day],
        requests_today=row[c.requests_today],
    )

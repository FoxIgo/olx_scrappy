"""Write one extraction outcome (sync answer or batch item) inside an open unit of work.

The single validation path of ADR 0007/0010: stale check -> domain validation -> store with
provenance -> relevance on every search link -> extraction state. Sync and batch mode both
use it, so a batch result is treated exactly like a sync answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from scrappy.application.ports.extractor import (
    ExtractionRejection,
    ExtractionResult,
    RejectionKind,
)
from scrappy.application.ports.unit_of_work import UnitOfWork
from scrappy.domain.category import CategoryCatalog
from scrappy.domain.extraction import (
    ExtractionRetryPolicy,
    ExtractionState,
    ExtractionTarget,
    OfferExtraction,
)
from scrappy.domain.offer import ContentHash, OfferId
from scrappy.domain.shared import InvalidValueError


class IngestStatus(StrEnum):
    STORED = "stored"
    FAILED = "failed"
    """Counted against the offer: backoff, parked after N failures."""
    RELEASED = "released"
    """Given back without penalty (quota / unavailable profile)."""
    STALE = "stale"
    """Discarded: the offer changed, the catalog changed, or another owner took it over."""


@dataclass(frozen=True, slots=True)
class IngestContext:
    """Everything about where the outcome came from (provenance + lease owner)."""

    profile: str
    provider: str
    prompt_version: str
    """The profile's prompt version (the backlog target)."""
    catalog_fingerprint: str
    """Fingerprint of the catalog the input was built with."""
    owner: str
    """Lease owner that claimed the offer (``sync:...`` or ``batch:...``)."""
    batch_id: str | None = None
    cost_estimated: bool = False


@dataclass(frozen=True, slots=True)
class IngestResult:
    status: IngestStatus
    kind: RejectionKind | None = None
    error: str | None = None
    extraction: OfferExtraction | None = None


async def ingest_outcome(
    uow: UnitOfWork,
    *,
    offer_id: OfferId,
    content_hash: ContentHash,
    outcome: ExtractionResult | ExtractionRejection,
    context: IngestContext,
    catalog: CategoryCatalog,
    retry: ExtractionRetryPolicy,
    now: datetime,
) -> IngestResult:
    offer = await uow.offers.get(offer_id)
    state = await uow.extraction_states.get(offer_id) or ExtractionState.new(offer_id, now)
    owned = state.lease_owner == context.owner
    if not owned and state.is_leased(now):
        return IngestResult(IngestStatus.STALE, error="leased by another owner")
    if (
        offer is None
        or offer.content_hash != content_hash
        or catalog.fingerprint != context.catalog_fingerprint
    ):
        if owned:
            state.release(now)
            await uow.extraction_states.save(state)
        return IngestResult(IngestStatus.STALE, error="offer or catalog changed meanwhile")

    target = ExtractionTarget(content_hash, catalog.fingerprint, context.prompt_version)
    if isinstance(outcome, ExtractionRejection):
        kind = outcome.rejection_kind
        if kind.penalizes_offer:
            state.record_failure(target, f"{kind.value}: {outcome.reason}", now, retry)
            status = IngestStatus.FAILED
        else:
            state.release(now)
            status = IngestStatus.RELEASED
        await uow.extraction_states.save(state)
        return IngestResult(status, kind, outcome.reason)

    try:
        extraction = OfferExtraction.validated(
            offer_id=offer_id,
            category=outcome.category,
            raw_attributes=outcome.attributes,
            catalog=catalog,
            model=outcome.model,
            prompt_version=context.prompt_version,  # the profile declares what it renders
            content_hash=content_hash,
            extracted_at=now,
            usage=outcome.usage,
            notes=outcome.notes,
            catalog_fingerprint=catalog.fingerprint,
            profile=context.profile,
            provider=context.provider,
            batch_id=context.batch_id,
            cost_estimated=context.cost_estimated,
        )
    except InvalidValueError as error:
        reason = f"invalid extraction: {error}"
        state.record_failure(target, f"{RejectionKind.INVALID_OUTPUT.value}: {reason}", now, retry)
        await uow.extraction_states.save(state)
        return IngestResult(IngestStatus.FAILED, RejectionKind.INVALID_OUTPUT, reason)

    await uow.extractions.add(extraction)
    for link in await uow.search_offers.list_for_offer(offer_id):
        search = await uow.searches.get(link.search)
        if search is None:
            continue
        link.update_relevance(search, extraction)
        await uow.search_offers.save(link)
    state.record_success(now)
    await uow.extraction_states.save(state)
    return IngestResult(IngestStatus.STORED, extraction=extraction)
